from django.http import HttpResponse, Http404
from rest_framework.views import APIView
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
