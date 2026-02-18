import requests

try:
    response = requests.get('http://localhost:5000/api/fortigate/wan/status')
    print('Status Code:', response.status_code)
    if response.status_code == 200:
        data = response.json()
        print('Success:', data.get('success'))
        print('Total WAN interfaces:', data.get('total', 0))
        for wan in data.get('wan_interfaces', []):
            print(f'{wan["interface"]}: {wan["status_geral"]} - IP: {wan["ip"]}')
    else:
        print('Response:', response.text)
except Exception as e:
    print('Error:', e)