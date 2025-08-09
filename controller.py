import kopf
import kubernetes
import requests
import random
import string
import os

kubernetes.config.load_incluster_config()
api = kubernetes.client.CoreV1Api()
apps_api = kubernetes.client.AppsV1Api()
networking_api = kubernetes.client.NetworkingV1Api()

# Configuration
CF_API_URL = "https://api.cloudflare.com/client/v4"
CLOUDFLARE_API_TOKEN = "your cloudflare API token"
HAPROXY_NODE_IP = "loadbalancer node IP"  ## if you have loadbalancer
CLOUDFLARE_ZONE_NAME = "your domain"

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
    "Content-Type": "application/json"
})

def generate_random_string(length=8):
    """Generate a lowercase alphanumeric string"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def get_zone_id(domain_name):
    response = session.get(f"{CF_API_URL}/zones")
    response.raise_for_status()
    zones = response.json()['result']
    for zone in zones:
        if zone['name'] == domain_name:
            return zone['id']
    raise Exception(f"Zone {domain_name} not found")

def get_existing_dns_record(zone_id, subdomain):
    response = session.get(f"{CF_API_URL}/zones/{zone_id}/dns_records?name={subdomain}")
    response.raise_for_status()
    results = response.json()['result']
    return results[0] if results else None

def delete_dns_record(zone_id, record_id):
    response = session.delete(f"{CF_API_URL}/zones/{zone_id}/dns_records/{record_id}")
    response.raise_for_status()

def create_dns_record(subdomain, domain_name, haproxy_ip):
    zone_id = get_zone_id(domain_name)
    fqdn = f"{subdomain}.{domain_name}".lower()  # Ensure lowercase

    existing = get_existing_dns_record(zone_id, fqdn)
    if existing:
        delete_dns_record(zone_id, existing['id'])
    
    record = {
        "type": "A",
        "name": fqdn,
        "content": haproxy_ip,
        "ttl": 1,
        "proxied": False
    }

    response = session.post(f"{CF_API_URL}/zones/{zone_id}/dns_records", json=record)
    response.raise_for_status()
    return response.json()['result']['id']

def delete_if_exists(resource_name, resource_type, namespace):
    try:
        if resource_type == "service":
            api.delete_namespaced_service(name=resource_name, namespace=namespace)
        elif resource_type == "deployment":
            apps_api.delete_namespaced_deployment(name=resource_name, namespace=namespace)
        elif resource_type == "ingress":
            networking_api.delete_namespaced_ingress(name=resource_name, namespace=namespace)
        elif resource_type == "configmap":
            api.delete_namespaced_config_map(name=resource_name, namespace=namespace)
    except kubernetes.client.exceptions.ApiException as e:
        if e.status != 404:
            raise

def create_configmap(name, namespace, html):
    configmap_name = f"{name}-html"
    delete_if_exists(configmap_name, "configmap", namespace)
    
    configmap = kubernetes.client.V1ConfigMap(
        metadata=kubernetes.client.V1ObjectMeta(name=configmap_name),
        data={"index.html": html}
    )
    
    try:
        api.create_namespaced_config_map(namespace=namespace, body=configmap)
    except kubernetes.client.exceptions.ApiException as e:
        if e.status == 409:
            api.replace_namespaced_config_map(
                name=configmap_name,
                namespace=namespace,
                body=configmap
            )
        else:
            raise

def create_deployment(name, namespace):
    delete_if_exists(name, "deployment", namespace)

    container = kubernetes.client.V1Container(
        name='nginx',
        image='nginx:latest',
        volume_mounts=[kubernetes.client.V1VolumeMount(
            mount_path='/usr/share/nginx/html', 
            name='html-volume'
        )]
    )
    
    volumes = [kubernetes.client.V1Volume(
        name='html-volume', 
        config_map=kubernetes.client.V1ConfigMapVolumeSource(
            name=f"{name}-html"
        )
    )]
    
    deployment = kubernetes.client.V1Deployment(
        metadata=kubernetes.client.V1ObjectMeta(name=name),
        spec=kubernetes.client.V1DeploymentSpec(
            replicas=1,
            selector=kubernetes.client.V1LabelSelector(
                match_labels={"app": name}
            ),
            template=kubernetes.client.V1PodTemplateSpec(
                metadata=kubernetes.client.V1ObjectMeta(
                    labels={"app": name}
                ),
                spec=kubernetes.client.V1PodSpec(
                    containers=[container], 
                    volumes=volumes
                )
            )
        )
    )
    
    apps_api.create_namespaced_deployment(namespace=namespace, body=deployment)

def create_service(name, namespace):
    delete_if_exists(name, "service", namespace)

    service = kubernetes.client.V1Service(
        metadata=kubernetes.client.V1ObjectMeta(name=name),
        spec=kubernetes.client.V1ServiceSpec(
            selector={"app": name},
            ports=[kubernetes.client.V1ServicePort(
                port=80, 
                target_port=80
            )]
        )
    )
    api.create_namespaced_service(namespace=namespace, body=service)

def create_ingress(name, namespace, fqdn):
    delete_if_exists(name, "ingress", namespace)

    # Ensure the FQDN is lowercase for Kubernetes compatibility
    fqdn = fqdn.lower()
    
    ingress = kubernetes.client.V1Ingress(
        metadata=kubernetes.client.V1ObjectMeta(name=name),
        spec=kubernetes.client.V1IngressSpec(
            rules=[kubernetes.client.V1IngressRule(
                host=fqdn,
                http=kubernetes.client.V1HTTPIngressRuleValue(
                    paths=[kubernetes.client.V1HTTPIngressPath(
                        path='/',
                        path_type='Prefix',
                        backend=kubernetes.client.V1IngressBackend(
                            service=kubernetes.client.V1IngressServiceBackend(
                                name=name,
                                port=kubernetes.client.V1ServiceBackendPort(number=80)
                            )
                        )
                    )]
                )
            )]
        )
    )
    networking_api.create_namespaced_ingress(namespace=namespace, body=ingress)

@kopf.on.create('devops.greenplus.com', 'v1alpha1', 'staticsites')
def create_static_site(spec, name, namespace, logger, **kwargs):
    try:
        subdomain_prefix = spec.get('subdomain', name).lower()  # Ensure lowercase prefix
        random_string = generate_random_string(8)
        subdomain = f"{subdomain_prefix}-{random_string}"
        fqdn = f"{subdomain}.{CLOUDFLARE_ZONE_NAME}".lower()  # Ensure lowercase FQDN

        create_configmap(name, namespace, spec['content'])
        create_deployment(name, namespace)
        create_service(name, namespace)
        create_ingress(name, namespace, fqdn)
        create_dns_record(subdomain, CLOUDFLARE_ZONE_NAME, HAPROXY_NODE_IP)
        
        logger.info(f"Static site '{name}' created and available at http://{fqdn}")
        return {'fqdn': fqdn}
        
    except Exception as e:
        logger.error(f"Failed to create static site {name}: {str(e)}")
        raise 
