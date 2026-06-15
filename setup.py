from setuptools import find_packages, setup

setup(
    name='netbox-librenms',
    version='0.1.0',
    description='A NetBox plugin to integrate LibreNMS monitoring data, interfaces, and LLDP neighbors.',
    long_description='A NetBox plugin to retrieve and display live monitoring status, interface details (IP, VLAN), and LLDP neighbor connections from LibreNMS.',
    url='https://github.com/ichha/netbox-librenms',
    author='Antigravity',
    author_email='antigravity@example.com',
    license='Apache-2.0',
    install_requires=[
        'requests',
    ],
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)
