from django.http import HttpResponse, Http404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from dcim.models import Device
from netbox_librenms.utils import LibreNMSClient
from netbox_librenms.views import get_librenms_device

class DeviceGraphProxyView(APIView):
    """
    Secure proxy endpoint that queries graph images from LibreNMS via backend API,
    preventing CORS errors and keeping credentials hidden from client-side requests.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            device = Device.objects.get(pk=pk)
        except Device.DoesNotExist:
            raise Http404("Device not found in NetBox")

        client = LibreNMSClient()
        if not client.is_configured():
            return HttpResponse("LibreNMS integration settings are missing.", status=400)

        # Retrieve request parameters
        graph_type = request.query_params.get('type', 'device_processor')
        range_val = request.query_params.get('range', '-1d')

        # Match NetBox device to LibreNMS
        librenms_device = get_librenms_device(client, device)
        if not librenms_device:
            return HttpResponse("Device not found in LibreNMS database.", status=404)

        device_id = librenms_device.get('device_id')
        if not device_id:
            return HttpResponse("Invalid LibreNMS device id mapping.", status=404)

        try:
            # Query graph stream from LibreNMS
            response = client.get_graph_image(device_id, graph_type, range_val)
            
            # Render and cache response stream
            django_response = HttpResponse(
                response.content,
                content_type=response.headers.get('Content-Type', 'image/png'),
                status=response.status_code
            )
            django_response['Cache-Control'] = 'private, max-age=60'
            return django_response
        except Exception as e:
            return HttpResponse(f"Error fetching graph: {str(e)}", status=500)


class LibreNMSTrafficDataView(APIView):
    """
    Secure proxy API view that fetches live interface graphs or JSON stats from LibreNMS
    based on device name and interface name.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        device_name = request.query_params.get("device")
        interface_name = request.query_params.get("interface")
        time_range = request.query_params.get("range", "1d")

        width_str = request.query_params.get("width")
        height_str = request.query_params.get("height")
        try:
            width = int(width_str) if width_str else 1350
        except ValueError:
            width = 1350
        try:
            height = int(height_str) if height_str else 350
        except ValueError:
            height = 350

        if not device_name or not interface_name:
            return Response(
                {"error": "Missing device or interface query parameters"},
                status=status.HTTP_400_BAD_REQUEST
            )

        client = LibreNMSClient()
        if not client.is_configured():
            return Response(
                {"error": "LibreNMS integration settings are missing."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 1. Look up NetBox device to extract primary IPv4/IPv6 address if possible
        nb_device = Device.objects.filter(name=device_name).first()
        if nb_device:
            librenms_device = get_librenms_device(client, nb_device)
        else:
            librenms_device = client.get_device(device_name)

        if not librenms_device:
            return Response(
                {"error": f"Device '{device_name}' not found in LibreNMS"},
                status=status.HTTP_404_NOT_FOUND
            )

        device_id = librenms_device.get('device_id') or librenms_device.get('hostname')
        if not device_id:
            return Response(
                {"error": "Invalid LibreNMS device id mapping."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if user wants JSON format instead of image
        accept_header = request.headers.get("Accept", "")
        wants_json = request.query_params.get("format") == "json" or "application/json" in accept_header

        if wants_json:
            try:
                stats = client.get_port_statistics(device_id, interface_name)
                if not stats:
                    stats = {
                        "in_bps": 0.0,
                        "out_bps": 0.0,
                        "port_id": None,
                        "ifSpeed": None
                    }
                
                response_data = {
                    "device": device_name,
                    "interface": interface_name,
                    "stats": {
                        "in": { "last": stats["in_bps"], "avg": stats["in_bps"], "max": stats["in_bps"] },
                        "out": { "last": stats["out_bps"], "avg": stats["out_bps"], "max": stats["out_bps"] }
                    },
                    "history": { "in": [], "out": [] }
                }
                return Response(response_data)
            except Exception as e:
                return Response(
                    {"error": f"Failed to retrieve port statistics: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        # Serve graph image (with single/double encoding fallback)
        try:
            response = client.get_port_graph_image(
                device_id=device_id,
                port_name=interface_name,
                time_range=time_range,
                double_encode=False,
                width=width,
                height=height
            )
            
            content_type = response.headers.get("Content-Type", "").lower()
            if "image/" not in content_type:
                raise ValueError("Response was not an image (single encoding)")
                
            return HttpResponse(response.content, content_type=content_type)
        except Exception as single_err:
            try:
                response = client.get_port_graph_image(
                    device_id=device_id,
                    port_name=interface_name,
                    time_range=time_range,
                    double_encode=True,
                    width=width,
                    height=height
                )
                
                content_type = response.headers.get("Content-Type", "").lower()
                if "image/" not in content_type:
                    raise ValueError("Response was not an image (double encoding)")
                    
                return HttpResponse(response.content, content_type=content_type)
            except Exception as double_err:
                err_msg = f"Failed to fetch graph via both single and double encoding. Single error: {str(single_err)}. Double error: {str(double_err)}"
                return Response(
                    {"error": err_msg},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
