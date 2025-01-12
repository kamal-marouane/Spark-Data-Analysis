# Definition of local variables
locals {
  base_apis = [
    "container.googleapis.com"
  ]
}

# Enable Google Cloud APIs
module "enable_google_apis" {
  source  = "terraform-google-modules/project-factory/google//modules/project_services"
  version = "~> 17.0"

  project_id = var.project_id

  # activate_apis is the set of base_apis
  activate_apis = local.base_apis
}

provider "kubernetes" {
  host                   = "https://${google_container_cluster.kafka_cluster.endpoint}"
  token                  = data.google_client_config.default.access_token
  cluster_ca_certificate = base64decode(google_container_cluster.kafka_cluster.master_auth.0.cluster_ca_certificate)
}

provider "helm" {
  kubernetes {
    host                   = "https://${google_container_cluster.kafka_cluster.endpoint}"
    token                  = data.google_client_config.default.access_token
    cluster_ca_certificate = base64decode(google_container_cluster.kafka_cluster.master_auth.0.cluster_ca_certificate)
  }
}

data "google_client_config" "default" {}

# Create GKE cluster
resource "google_container_cluster" "kafka_cluster" {
  name     = var.cluster_name
  location = var.zone
  project  = var.project_id

  initial_node_count = 3
  node_config {
    machine_type = "e2-standard-2"
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }

  deletion_protection = false

  depends_on = [
    module.enable_google_apis
  ]
}

# Create namespace for Kafka
resource "kubernetes_namespace" "kafka" {
  metadata {
    name = "kafka"
  }
  depends_on = [
    google_container_cluster.kafka_cluster
  ]
}

output "kubeconfig" {
  value = google_container_cluster.kafka_cluster.endpoint
}

output "endpoint" {
  value = google_container_cluster.kafka_cluster.endpoint
}