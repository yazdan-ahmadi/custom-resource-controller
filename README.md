Perfect — here's the final compact version of the task with the focus on subdomain creation in Cloudflare:

---

## ✅ DevOps Task: Deploy Nginx Site & Register Subdomain via CRD

### 🎯 Goal:

Create a Kubernetes Custom Resource (StaticSite) that triggers:

1. Deployment of a static Nginx website.
2. Exposure via Service + Ingress.
3. Creation of a subdomain DNS record in Cloudflare, assuming the root domain (e.g. example.com) is already set up.

---

### 📦 CRD: `StaticSite`

apiVersion: devops.mycompany.com/v1alpha1
kind: StaticSite
metadata:
  name: blog
spec:
  subdomain: blog
  content: |
    <html><body><h1>Welcome to Blog!</h1></body></html>

> This will serve the site at blog.example.com

---

### 👨‍💻 Controller Responsibilities:

* Watch StaticSite CRs.
* Create:

  * ConfigMap with HTML from spec.content
  * Nginx Deployment using it
  * Service + Ingress for access
* Register blog.example.com in Cloudflare:

  * Create a CNAME or A record under the existing root domain example.com
  * Use Cloudflare API with credentials from a K8s Secret

---

### 🧰 Stack:

* Python + Kopf for controller
* Cloudflare API
* Ingress Controller (already in cluster)
* Cloudflare root domain already configured

---

### 🧠 Skills Learned:

* Declarative infra via CRDs
* Controller logic and reconciliation
* DNS automation for real-world DevOps scenarios

---

Let me know if you'd like:

* A YAML starter pack (CRD + sample CR)
* A minimal Python controller skeleton with Cloudflare support
