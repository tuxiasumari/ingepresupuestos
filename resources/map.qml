import QtQuick
import QtLocation
import QtPositioning

Item {
    id: root
    // Centro inicial y marcador (lo setea Python).
    property real centerLat: -12.0464
    property real centerLon: -77.0428
    property real markLat: 0
    property real markLon: 0
    property bool hasMark: false
    property int  startZoom: 14
    // Vista satelital on/off + si el proveedor la ofrece.
    property bool satelite: false
    property bool tieneSatelite: false

    // Emitida al hacer clic/tap en el mapa.
    signal picked(real lat, real lon)

    function _aplicarTipo() {
        // Satélite = SatelliteMapDay (Esri, definido en el repositorio local);
        // calle = StreetMap (OSM, definido en el repositorio local).
        var types = view.map.supportedMapTypes
        for (var i = 0; i < types.length; i++) {
            var st = types[i].style
            if (root.satelite && st === MapType.SatelliteMapDay) {
                view.map.activeMapType = types[i]; return
            }
            if (!root.satelite && st === MapType.StreetMap) {
                view.map.activeMapType = types[i]; return
            }
        }
    }
    function _detectarSatelite() {
        var types = view.map.supportedMapTypes
        for (var i = 0; i < types.length; i++)
            if (types[i].style === MapType.SatelliteMapDay) { root.tieneSatelite = true; return }
    }
    onSateliteChanged: _aplicarTipo()

    // Python llama a esto para centrar y/o poner el marcador.
    function centrar(lat, lon, zoom) {
        view.map.center = QtPositioning.coordinate(lat, lon)
        if (zoom > 0) view.map.zoomLevel = zoom
    }
    function marcar(lat, lon) {
        root.markLat = lat
        root.markLon = lon
        root.hasMark = true
        view.map.center = QtPositioning.coordinate(lat, lon)
    }

    // Las rutas absolutas (repositorio de proveedores y caché) las inyecta
    // Python como context properties ANTES de cargar el QML, para que el
    // Plugin nazca con ellas (los PluginParameter se leen una sola vez al
    // inicializar el plugin).
    Plugin {
        id: osmPlugin
        name: "osm"
        // Repositorio de proveedores LOCAL (bundle): define la capa de calles
        // (OpenStreetMap directo) y la satelital (Esri World Imagery) con URLs
        // SIN API key. El servicio hospedado por Qt (maps.qt.io) ya no sirve
        // tiles gratis en muchos zooms → devolvía mosaicos "API Key Required".
        PluginParameter {
            name: "osm.mapping.providersrepository.address"
            value: ingepProvidersUrl
        }
        // Caché propio de la app: el caché por defecto de QtLocation queda
        // contaminado con los mosaicos "API Key Required" ya descargados y los
        // seguiría sirviendo (la clave de caché es por id de tipo, no por URL).
        PluginParameter {
            name: "osm.mapping.cache.directory"
            value: ingepCacheDir
        }
        // Tiles de DPI estándar (los servidores libres no ofrecen @2x).
        PluginParameter { name: "osm.mapping.highdpi_tiles"; value: "false" }
    }

    MapView {
        id: view
        anchors.fill: parent
        map.plugin: osmPlugin
        map.center: QtPositioning.coordinate(root.centerLat, root.centerLon)
        map.zoomLevel: root.startZoom

        TapHandler {
            acceptedButtons: Qt.LeftButton
            onTapped: function(eventPoint) {
                var c = view.map.toCoordinate(eventPoint.position)
                root.markLat = c.latitude
                root.markLon = c.longitude
                root.hasMark = true
                root.picked(c.latitude, c.longitude)
            }
        }

        Component.onCompleted: {
            // Agregar el marcador al mapa explícitamente (en MapView no basta
            // declararlo como hijo).
            view.map.addMapItem(marker)
            root._detectarSatelite()
        }
    }

    // Pin del proyecto (solo rectángulos para que siempre se dibuje).
    MapQuickItem {
        id: marker
        visible: root.hasMark
        coordinate: QtPositioning.coordinate(root.markLat, root.markLon)
        anchorPoint.x: 14            // centro horizontal
        anchorPoint.y: 32            // la PUNTA del pin = punto exacto
        sourceItem: Item {
            width: 28; height: 32
            // Punta: cuadrado rotado 45° (la esquina inferior es la punta).
            Rectangle {
                width: 16; height: 16
                color: "#E11D2A"
                rotation: 45
                anchors.horizontalCenter: parent.horizontalCenter
                y: 9
            }
            // Cabeza circular roja con borde blanco + punto blanco.
            Rectangle {
                width: 26; height: 26; radius: 13
                color: "#E11D2A"
                border.color: "white"; border.width: 3
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                Rectangle {
                    width: 9; height: 9; radius: 4.5
                    color: "white"; anchors.centerIn: parent
                }
            }
        }
    }

    Connections {
        target: view.map
        function onSupportedMapTypesChanged() { root._detectarSatelite() }
    }
}
