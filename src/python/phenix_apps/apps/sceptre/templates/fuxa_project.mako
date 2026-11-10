<%doc>
Variables: opc_endpoint (e.g. opc.tcp://10.1.2.50:4840), view_name, project_name, view_w, view_h,
every string below goes through json.dumps so a quote or backslash cannot break the JSON;
points: list of Point (rtu.device.field) -> tag "t<N>" named/addressed "<node>" / "ns=2;s=<node>",
view_items, view_svg: JSON text from lock_view.
</%doc>\
<%! import json %>\
{
  "devices": {
    "0": {"id": "0", "name": "FUXA Server", "enabled": true, "type": "FuxaServer", "property": {}, "tags": {}},
    "d_opc": {
      "id": "d_opc", "name": "opc", "enabled": true, "type": "OPCUA", "polling": 1000,
      "property": {"address": ${json.dumps(opc_endpoint)}},
      "tags": {
% for i, p in enumerate(points, 1):
        "t${i}": {"id": "t${i}", "name": ${json.dumps(p.node)}, "type": "number",
          "address": ${json.dumps("ns=%s;s=%s" % (ns, p.node))}, "daq": {"enabled": false, "interval": 60, "restored": false}}${"," if i < len(points) else ""}
% endfor
      }
    }
  },
  "hmi": {
    "views": [
      {
        "id": "v_lock", "name": ${view_name}, "profile": {"width": ${view_w}, "height": ${view_h}, "bkcolor": "#ffffffff"},
        "variables": {},
        "items": ${view_items},
        "svgcontent": ${view_svg}
      }
    ],
    "layout": {"start": "v_lock", "navigation": {"mode": "void", "type": "inline", "items": []}, "header": {}}
  },
  "version": "1.01", "name": ${project_name}, "server": {"id": "0", "name": "FUXA Server", "type": "FuxaServer", "property": {}},
  "texts": [], "alarms": [], "recipes": []
}