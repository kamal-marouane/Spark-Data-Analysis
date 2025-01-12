# Extensions

## Overview
In this project, we set up a complete data pipeline for streaming data using Apache Kafka, Spark Structured Streaming, and Prometheus for metrics visualization via Grafana. All the setup was done on the Cloud, except for the execution of the producer and Spark job, which were executed locally as a proof of concept. We can easily set up an image and run it on GKE.

---

## Event Streaming
We chose Apache Kafka for our distributed data processing pipeline due to its robust scalability, fault tolerance, and ability to handle high-throughput streaming. Kafka excels at decoupling data producers and consumers, ensuring minimal latency in communication between systems. This attribute is critical for our project involving large-scale cluster analysis, where data must flow seamlessly from multiple sources into Spark for computation without bottlenecks. Kafka’s ability to persist messages ensures that even if consumers experience downtime, no data is lost.

Kafka's seamless integration with Spark streaming enables us to construct real-time dashboards and analyses. Spark can consume Kafka topics directly, facilitating real-time monitoring of metrics like CPU peaks and task evictions. Additionally, Kafka's compatibility with batch and stream processing frameworks makes it a versatile choice for analyzing historical data and real-time event streams.

### High-Level Design of Kafka
![Kafka High Level Design](readme_images/high_level_diagram_kafka.png)

---

## Producer Setup

### Explanation and Key Steps for Kafka Deployment
To deploy Kafka on Google Kubernetes Engine (GKE) and automate the process using Terraform, the following steps were performed:

#### 1. Enabling Google Cloud APIs
- The `container.googleapis.com` API is enabled to allow GKE cluster creation.

**Code Snippet:**
```hcl
locals {
  base_apis = [
    "container.googleapis.com"
  ]
}

module "enable_google_apis" {
  source  = "terraform-google-modules/project-factory/google//modules/project_services"
  version = "~> 17.0"

  project_id   = var.project_id
  activate_apis = local.base_apis
}
```
- **Purpose:** Ensures that the required APIs for managing GKE and other services are available.

---

#### 2. GKE Cluster Configuration
- Created a GKE cluster (`google_container_cluster.kafka_cluster`) with three nodes of type `e2-standard-2`.
- The nodes are assigned OAuth scopes for full cloud platform access.

**Code Snippet:**
```hcl
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
}
```
- **Purpose:** Provides a scalable infrastructure to host the Kafka cluster.

---

#### 3. Kafka Namespace Creation
- Created a Kubernetes namespace `kafka` for organizing Kafka-related resources.

**Code Snippet:**
```hcl
resource "kubernetes_namespace" "kafka" {
  metadata {
    name = "kafka"
  }
  depends_on = [
    google_container_cluster.kafka_cluster
  ]
}
```
- **Purpose:** Ensures Kafka components run in a dedicated namespace to avoid conflicts with other workloads.

---

#### 4. Deploying Kafka with Strimzi
- Applied the Strimzi Operator for managing Kafka on Kubernetes:
  ```bash
  kubectl create -f 'https://strimzi.io/install/latest?namespace=kafka' -n kafka
  ```
  - This installs the Strimzi custom resource definitions (CRDs) and necessary controllers.
- Applied a Kafka cluster configuration using Strimzi CRDs:
  ```yaml
  apiVersion: kafka.strimzi.io/v1beta2
  kind: Kafka
  metadata:
    name: kafka-cluster
    namespace: kafka
  spec:
    kafka:
      replicas: 2
      listeners:
        - name: plain
          port: 9092
          type: internal
          tls: false
        - name: external
          port: 9094
          type: loadbalancer
          tls: false
    zookeeper:
      replicas: 1
      storage:
        type: persistent-claim
        size: 10Gi
    entityOperator:
      topicOperator: {}
      userOperator: {}
  ```
- **Purpose:** Deploys a Kafka cluster (`kafka-cluster`) with two Kafka brokers and one Zookeeper node.

---

#### 5. Kafka Topics Creation
- Created two topics: `job-events` and `task-events`, each with 12 partitions and 2 replicas.

**Code Snippet:**
```yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaTopic
metadata:
  name: job-events
  namespace: kafka
spec:
  partitions: 12
  replicas: 2
  config:
    retention.ms: 1209600000  # 14 days retention
    segment.bytes: 1073741824  # 1GB segment size
---
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaTopic
metadata:
  name: task-events
  namespace: kafka
spec:
  partitions: 12
  replicas: 2
  config:
    retention.ms: 1209600000  # 14 days retention
    segment.bytes: 1073741824  # 1GB segment size
```
- **Purpose:** Ensures that job and task events are distributed across 12 partitions for parallel processing.

---

#### 6. Kafka UI Deployment
- Deployed a web-based Kafka UI (`Kafdrop`) for monitoring topics, partitions, and messages.

**Code Snippet:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kafka-ui
  namespace: kafka
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: kafka-ui
          image: obsidiandynamics/kafdrop:latest
          ports:
            - containerPort: 9000
          env:
            - name: KAFKA_BROKERCONNECT
              value: "kafka-cluster-kafka-bootstrap:9092"
```
- **Purpose:** Provides a visual interface for inspecting Kafka topics and debugging.

---

## Final Outcome
- The Kafka cluster was successfully configured and deployed on GKE.
- `job-events` and `task-events` topics were created with appropriate partitioning and replication.
- The Kafka UI (`Kafdrop`) was set up for monitoring the events being streamed.
![Kafka UI](readme_images/kafka-ui.png)
This setup ensures a robust Kafka deployment with visibility and scalability, aligned with the producer's requirements for handling `job-events` and `task-events`.

---

## Detailed Problematic: Ensuring Global Timestamp Ordering in Event Data Streams

### Context
We are working with two event datasets representing `job-events` and `task-events`. Each dataset is organized into folders containing multiple files with a specific schema. The files follow a strict local order within their respective datasets but lack global ordering when considered across the two folders.

#### Job Events Dataset
- **File pattern:** `job_events/part-?????-of-?????.csv.gz`
- **Fields:**
  1. `time` (INTEGER, mandatory)
  2. `missing info` (INTEGER, optional)
  3. `job ID` (INTEGER, mandatory)
  4. `event type` (INTEGER, mandatory)
  5. `user` (STRING_HASH, optional)
  6. `scheduling class` (INTEGER, optional)
  7. `job name` (STRING_HASH, optional)
  8. `logical job name` (STRING_HASH, optional)

- **Local Ordering:**
  Each file in the job-events folder is ordered by the `time` field. The last `time` value in one file is always less than the first `time` value in the subsequent file.

#### Task Events Dataset
- **File pattern:** `task_events/part-?????-of-?????.csv.gz`
- **Fields:**
  1. `time` (INTEGER, mandatory)
  2. `missing info` (INTEGER, optional)
  3. `job ID` (INTEGER, mandatory)
  4. `task index` (INTEGER, mandatory)
  5. `machine ID` (INTEGER, optional)
  6. `event type` (INTEGER, mandatory)
  7. `user` (STRING_HASH, optional)
  8. `scheduling class` (INTEGER, optional)
  9. `priority` (INTEGER, mandatory)
  10. `CPU request` (FLOAT, optional)
  11. `memory request` (FLOAT, optional)
  12. `disk space request` (FLOAT, optional)
  13. `different machines restriction` (BOOLEAN, optional)

- **Local Ordering:**
  Each file in the task-events folder is also ordered by the `time` field, with the same local ordering properties as the job-events dataset.

---

## Kafka Streaming Setup
- **Topics:** There are two Kafka topics: `job-events` and `task-events`.
- **Partitions:** Each topic is divided into 12 partitions.
- **Partitioning:** Data is partitioned based on specific keys (e.g., `job ID`, `task index`, etc.).
- **Ordering Guarantees:** Kafka guarantees ordering only within each partition, not across partitions or topics.

---

## Problem Statement
When streaming the job and task events to Kafka:
1. **Intra-File Order Preservation:** The events within each file retain their local order.
2. **Cross-Partition Order Loss:** Since events are partitioned, the consumer may receive events out of order when comparing across partitions.
3. **Cross-Topic Order Loss:** Events from `job-events` and `task-events` topics may arrive out of sequence relative to each other.

This results in the consumer receiving events with timestamps that may be earlier than the timestamps of previously received events.

---

## Key Objectives
- **Global Timestamp Consistency:** Ensure that events from both job-events and task-events follow a strict global order by `time` when consumed.
- **Seamless Streaming:** Handle partitioned data streams from Kafka so that downstream consumers do not process unordered events.

---

## Challenges
1. **Partitioned Data Streams:** Kafka partitions disrupt global ordering across partitions.
2. **Inter-Topic Synchronization:** There is no inherent synchronization between the two topics (`job-events` and `task-events`), leading to overlapping or unsynchronized event streams.
3. **Real-Time Buffering:** Merging and sorting events in real-time introduces additional complexity and may impact throughput.
4. **Balancing Latency and Throughput:** To maintain order, some events may need to be buffered, causing potential delays.

---

## Proposed Solution

### 1. Priority Queue for Global Ordering
- A **min-heap (priority queue)** is used to maintain the global order of events.
- Events from different files and folders are pushed into the heap, ensuring the smallest timestamped event is always at the top.

**Code Snippet:**
```python
import heapq  # Min-heap for global ordering

def stream_file_to_queue(topic, file_path, fields, priority_queue, counter):
    logging.info(f"Reading data from file '{file_path}' for topic '{topic}'...")
    for record in read_events(file_path, fields):
        timestamp = record.get("time")
        if timestamp is None or not isinstance(timestamp, int):
            logging.warning(f"Skipping record with invalid timestamp: {record}")
            continue
        try:
            # Push tuple (timestamp, counter, record) to maintain sorting by timestamp and insertion order
            heapq.heappush(priority_queue, (timestamp, counter, record))
            counter += 1
        except TypeError as e:
            logging.error(f"Error pushing to priority queue: {e}, record: {record}")
    logging.info(f"Finished reading file '{file_path}' for topic '{topic}'.")
```
- **Purpose:** Ensures that records are pushed into the priority queue with their `time` values.
- **Counter:** Used as a tie-breaker to maintain insertion order when timestamps are identical.

---

### 2. Sending Messages in Global Timestamp Order
- The `send_messages_from_queue` function dequeues the smallest timestamped event and sends it to Kafka.
- Events are assigned a partition based on their timestamp modulo the number of partitions (12 in this case).

**Code Snippet:**
```python
def send_messages_from_queue(priority_queue, producer):
    while priority_queue:
        timestamp, counter, record = heapq.heappop(priority_queue)  # Pop the earliest event
        topic = "job-events" if "task_index" not in record else "task-events"
        key = record.get("job_id", "default")

        # Partitioning logic to distribute records across 12 partitions
        partition = timestamp % 12  # 12 partitions
        producer.send(topic, key=key, value=record, partition=partition)
        logging.info(f"Sent event with timestamp {timestamp} to topic {topic}")
    producer.flush()
```
- **Purpose:** Sends records in strict timestamp order.
- **Partition Assignment:** Ensures consistent partitioning without disrupting the timestamp order within the same stream.

---

### 3. Start Streaming Across All Files and Topics
- The `start_streaming` function processes all files across `job-events` and `task-events`.
- For each file, the records are read, processed, and pushed into the priority queue.

**Code Snippet:**
```python
def start_streaming():
    priority_queue = []
    counter = 0  # Initialize the counter for tie-breaking
    for topic, mapping in field_mappings.items():
        for file_path in mapping["files"]:
            stream_file_to_queue(topic, file_path, mapping["fields"], priority_queue, counter)
    send_messages_from_queue(priority_queue, producer)
```
- **Purpose:** Combines both folders' streams into a single globally sorted stream.
- **Priority Queue:** Ensures that records are sent in timestamp order regardless of their original file or folder.

---

## Spark Streaming Job

### 1. Spark Streaming Setup
- **Purpose:** Read from Kafka topics and process the streaming data in real time.
- **Configuration:**
  - `spark.jars.packages`: Loads Kafka and Prometheus libraries.
  - **Kafka Broker:** `34.45.123.229:9094`.

**Key Schema Components:**
- **Task Events Schema:**
  ```python
  StructType([
      StructField("time", LongType(), True),
      StructField("job_id", IntegerType(), True),
      StructField("machine_id", IntegerType(), True),
      StructField("cpu_request", FloatType(), True),
      StructField("memory_request", FloatType(), True)
  ])
  ```

---

### 2. Resource Usage Aggregation
- **Aggregates:**
  - `sum("cpu_request")`: Total CPU usage per machine.
  - `sum("memory_request")`: Total memory usage per machine.
  - `avg("cpu_request")`: Average CPU request per task.
  - `avg("memory_request")`: Average memory request per task.

**Streaming Logic:**
```python
resource_usage = task_data.groupBy(
    window(col("event_time"), "1 minute"),
    "machine_id"
).agg(
    sum("cpu_request").alias("total_cpu_usage"),
    sum("memory_request").alias("total_memory_usage"),
    avg("cpu_request").alias("avg_cpu_request_per_task"),
    avg("memory_request").alias("avg_memory_request_per_task")
)
```

---

## Prometheus and Grafana Integration

### 1. Prometheus Setup
- Created a namespace called `monitoring`:
  ```bash
  kubectl create namespace monitoring
  ```
- Installed Prometheus using Helm:
  ```bash
  helm install prometheus prometheus-community/prometheus -f prometheus.yaml -n monitoring
  ```
- Exposed Prometheus to make it accessible outside of the cluster:
  ```bash
  kubectl patch svc prometheus-server -n monitoring -p '{"spec": {"type": "LoadBalancer"}}'
  ```

---

### 2. Spark to Prometheus
- **Prometheus Push Function:**
  ```python
  def push_to_prometheus(batch_df, _):
      registry = CollectorRegistry()
      cpu_gauge = Gauge('total_cpu_usage', 'CPU usage', ['machine_id'], registry=registry)
      memory_gauge = Gauge('total_memory_usage', 'Memory usage', ['machine_id'], registry=registry)

      for row in batch_df.collect():
          cpu_gauge.labels(machine_id=row.machine_id).set(float(row.total_cpu_usage))
          memory_gauge.labels(machine_id=row.machine_id).set(float(row.total_memory_usage))

      push_to_gateway(PUSHGATEWAY_URL, job='spark_job_metrics', registry=registry)
  ```

---

## Grafana Dashboard Setup

### 1. Installation
- Installed Grafana using Helm:
  ```bash
  helm install my-grafana grafana/grafana --namespace monitoring
  ```
- Exposed Grafana to make it accessible outside the cluster:
  ```bash
  kubectl patch svc my-grafana -n monitoring -p '{"spec": {"type": "LoadBalancer"}}'
  ```

---

### 2. Configuration of Prometheus Data Source
- **Steps:**
  1. Open Grafana → Configuration → Data Sources.
  2. Add **Prometheus** as a new data source.
  3. **URL:** Replace with the external Prometheus URL (e.g., `EXTERNAL_URL_PROMETHEUS`).

---

### 3. Creating the Dashboard
- **Importing the Prebuilt Dashboard:**
  1. Navigate to the `spark/grafana-dashboard` folder.
  2. Import the `spark.json` file.
  3. Configure the imported panels to visualize CPU and memory usage trends.

---

## How to Run the Producer and Spark Job

### 1. Producer Setup
To get the **Kafka Broker IP**:
- Run the following command to get the external IP address of the `kafka-cluster-kafka-external-bootstrap` service:
  ```bash
  kubectl get svc -n kafka
  ```

To get the **PushGateway URL**:
- Run the following command to get the external IP address of the Prometheus PushGateway:
  ```bash
  kubectl get svc -n monitoring
  ```

- Update the `bootstrap_servers` in the producer configuration:
  ```yaml
  kafka:
    bootstrap_servers: "YOUR_KAFKA_BROKER_IP:9094"  # Replace with the external Kafka broker IP.
    batch_size: 32768  # Reduce to smaller batches for better performance.
    linger_ms: 100  # Small wait time to batch more messages.
    buffer_memory: 67108864  # 64 MB buffer to avoid overflow.
    simulation_duration: 60  # Run the simulation for 60 seconds.

    topics:
      job-events: "job-events"
      task-events: "task-events"
    time_scaling_factor: 1000000  # Handle microsecond timestamps.
  ```

### 2. Running the Producer Script
- Run the producer script with the correct IP addresses:
  ```bash
  python3 test.py -PUSHGATEWAY_URL="http://YOUR_PUSHGATEWAY_IP:9091" -KAFKA_BROKER="YOUR_KAFKA_BROKER_IP:9094"
  ```

---

### 3. Grafana Visualization
- Confirm that CPU and memory usage trends are displayed correctly.
- The customized dashboard allows for real-time streaming data visualization.

![Grafana Dashboard Screenshot](readme_images/grafana.png)

---

## Conclusion
In this project, we successfully built a real-time data pipeline using Kafka on the cloud, Spark Structured Streaming, and Prometheus for monitoring. Integration with Grafana provided powerful visualizations and insights into CPU and memory usage across different machines. This robust setup ensures efficient event streaming, real-time resource monitoring, and scalability for future enhancements.


