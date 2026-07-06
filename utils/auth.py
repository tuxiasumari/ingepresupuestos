# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Autenticación de usuarios (equivale a Flask-Login + werkzeug en app.py)."""
import sqlite3
import json
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash

from core.config import DB_PATH, SESSION_FILE
from models.usuario import Usuario


_usuario_actual: Usuario | None = None

# Archivo donde se guarda la sesión recordada (cross-platform, en USER_DATA_DIR)
_SESSION_FILE = SESSION_FILE


def _fila_a_usuario(row) -> Usuario:
    return Usuario(
        id=row['id'],
        nombre=row['nombre'],
        username=row['username'] or row['nombre'],
        email=row['email'] or '',
        password_hash=row['password_hash'],
        rol=row['rol'],
        activo=row['activo'],
        creado_en=row['creado_en'] or '',
    )


def usuario_actual() -> Usuario | None:
    return _usuario_actual


def login(username: str, password: str) -> tuple[bool, str]:
    """Retorna (ok, mensaje). Carga _usuario_actual si ok=True."""
    global _usuario_actual
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM usuarios WHERE (username=? OR email=?) AND activo=1",
            (username, username)
        ).fetchone()
        conn.close()
    except sqlite3.Error as e:
        return False, f"Error de base de datos: {e}"

    if not row:
        return False, "Usuario no encontrado"
    if not check_password_hash(row['password_hash'], password):
        return False, "Contraseña incorrecta"

    _usuario_actual = _fila_a_usuario(row)
    return True, "OK"


def logout():
    global _usuario_actual
    _usuario_actual = None
    borrar_sesion()


# ── Sesión recordada ──────────────────────────────────────────────────────────

def guardar_sesion(usuario: Usuario):
    """Guarda el ID del usuario en disco para recuperar la sesión al reiniciar."""
    try:
        _SESSION_FILE.write_text(
            json.dumps({"user_id": usuario.id}), encoding="utf-8"
        )
    except OSError:
        pass


def cargar_sesion() -> Usuario | None:
    """Lee la sesión guardada y devuelve el Usuario si sigue activo en la BD."""
    if not _SESSION_FILE.exists():
        return None
    try:
        data    = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
        user_id = data.get("user_id")
        if not user_id:
            return None
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM usuarios WHERE id=? AND activo=1", (user_id,)
        ).fetchone()
        conn.close()
        if not row:
            borrar_sesion()
            return None
        return _fila_a_usuario(row)
    except Exception:
        borrar_sesion()
        return None


def borrar_sesion():
    """Elimina el archivo de sesión (al hacer logout o cambiar de usuario)."""
    try:
        if _SESSION_FILE.exists():
            _SESSION_FILE.unlink()
    except OSError:
        pass


def hay_usuarios() -> bool:
    """False si la BD está vacía → mostrar pantalla de setup."""
    try:
        conn = sqlite3.connect(DB_PATH)
        n = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        conn.close()
        return n > 0
    except sqlite3.Error:
        return False


def crear_admin(nombre: str, username: str, password: str,
                email: str = '', rol: str = 'admin') -> tuple[bool, str]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Verificar duplicados antes de insertar para dar mensajes claros
        if conn.execute("SELECT 1 FROM usuarios WHERE username=?", (username,)).fetchone():
            return False, f"El usuario «{username}» ya existe. Elige otro nombre."
        if email and conn.execute("SELECT 1 FROM usuarios WHERE email=?", (email,)).fetchone():
            return False, f"El correo «{email}» ya está registrado."

        conn.execute(
            "INSERT INTO usuarios (nombre, username, email, password_hash, rol, activo)"
            " VALUES (?,?,?,?,?,1)",
            (nombre, username, email, generate_password_hash(password), rol)
        )
        conn.commit()
        return True, "Usuario creado"
    except sqlite3.Error as e:
        err = str(e).lower()
        if "username" in err:
            return False, f"El usuario «{username}» ya existe. Elige otro nombre."
        if "email" in err:
            return False, f"El correo «{email}» ya está registrado."
        return False, f"Error al crear la cuenta: {e}"
    finally:
        conn.close()


def listar_usuarios() -> list[Usuario]:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM usuarios ORDER BY creado_en"
        ).fetchall()
        conn.close()
        return [_fila_a_usuario(r) for r in rows]
    except sqlite3.Error:
        return []


def actualizar_usuario(user_id: int, nombre: str, username: str,
                       email: str, rol: str) -> tuple[bool, str]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        dup = conn.execute(
            "SELECT 1 FROM usuarios WHERE username=? AND id!=?",
            (username, user_id)
        ).fetchone()
        if dup:
            return False, f"El usuario «{username}» ya existe."
        if email:
            dup_e = conn.execute(
                "SELECT 1 FROM usuarios WHERE email=? AND id!=?",
                (email, user_id)
            ).fetchone()
            if dup_e:
                return False, f"El correo «{email}» ya está registrado."
        conn.execute(
            "UPDATE usuarios SET nombre=?, username=?, email=?, rol=? WHERE id=?",
            (nombre, username, email, rol, user_id)
        )
        conn.commit()
        return True, "Usuario actualizado"
    except sqlite3.Error as e:
        return False, f"Error: {e}"
    finally:
        conn.close()


def cambiar_password(user_id: int, password: str) -> tuple[bool, str]:
    if len(password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE usuarios SET password_hash=? WHERE id=?",
            (generate_password_hash(password), user_id)
        )
        conn.commit()
        conn.close()
        return True, "Contraseña actualizada"
    except sqlite3.Error as e:
        return False, f"Error: {e}"


def toggle_activo(user_id: int) -> tuple[bool, str]:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT activo FROM usuarios WHERE id=?", (user_id,)).fetchone()
        if not row:
            conn.close()
            return False, "Usuario no encontrado"
        nuevo = 0 if row['activo'] else 1
        conn.execute("UPDATE usuarios SET activo=? WHERE id=?", (nuevo, user_id))
        conn.commit()
        conn.close()
        estado = "activado" if nuevo else "desactivado"
        return True, f"Usuario {estado}"
    except sqlite3.Error as e:
        return False, f"Error: {e}"


def eliminar_usuario(user_id: int) -> tuple[bool, str]:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM usuarios WHERE id=?", (user_id,))
        conn.commit()
        conn.close()
        return True, "Usuario eliminado"
    except sqlite3.Error as e:
        return False, f"Error: {e}"


def login_invitado():
    """Establece una sesión de invitado sin autenticación."""
    global _usuario_actual
    _usuario_actual = Usuario(
        id=0,
        nombre="Invitado",
        username="invitado",
        email="",
        password_hash="",
        rol="invitado",
        activo=1,
        creado_en="",
    )
