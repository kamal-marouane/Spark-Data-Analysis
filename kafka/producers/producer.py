import csv
import gzip
import json
import time
import yaml
import logging
import os
import heapq  # Min-heap for global ordering
from kafka import KafkaProducer

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load configuration from YAML file
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Define the base directories for job-events and task-events
job_events_dir = "../../dataset/job_events"
task_events_dir = "../../dataset/task_events"

# Field mappings for each topic
# Updated field mappings for all columns
field_mappings = {
    "job-events": {
        "files": sorted([os.path.join(job_events_dir, f) for f in os.listdir(job_events_dir) if f.endswith(".csv.gz")]),
        "fields": [
            {"name": "time", "type": int},
            {"name": "missing_info", "type": int},
            {"name": "job_id", "type": int},
            {"name": "event_type", "type": int},
            {"name": "user", "type": str},
            {"name": "scheduling_class", "type": int},
            {"name": "job_name", "type": str},
            {"name": "logical_job_name", "type": str}
        ]
    },
    "task-events": {
        "files": sorted([os.path.join(task_events_dir, f) for f in os.listdir(task_events_dir) if f.endswith(".csv.gz")]),
        "fields": [
            {"name": "time", "type": int},
            {"name": "missing_info", "type": int},
            {"name": "job_id", "type": int},
            {"name": "task_index", "type": int},
            {"name": "machine_id", "type": int},
            {"name": "event_type", "type": int},
            {"name": "user", "type": str},
            {"name": "scheduling_class", "type": int},
            {"name": "priority", "type": int},
            {"name": "cpu_request", "type": float},
            {"name": "memory_request", "type": float},
            {"name": "disk_space_request", "type": float},
            {"name": "different_machines_restriction", "type": bool}
        ]
    }
}


# Kafka producer initialization
producer = KafkaProducer(
    bootstrap_servers=config["kafka"]["bootstrap_servers"],
    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    key_serializer=lambda v: str(v).encode('utf-8')
)

# Function to read and yield events from a file
def read_events(file_path, fields):
    with gzip.open(file_path, 'rt') as f:
        reader = csv.reader(f)
        for row in reader:
            record = {}
            for i, field in enumerate(fields):
                value = row[i] if i < len(row) else None
                if value is None or value.strip() == '':
                    value = 0 if field["type"] in [int, float] else "unknown"
                else:
                    try:
                        value = field["type"](value)
                    except (ValueError, TypeError):
                        value = 0 if field["type"] in [int, float] else "unknown"
                record[field["name"]] = value
            yield record

# Function to stream data for a single file and push to the priority queue
def stream_file_to_queue(topic, file_path, fields, priority_queue, counter):
    logging.info(f"Reading data from file '{file_path}' for topic '{topic}'...")
    for record in read_events(file_path, fields):
        timestamp = record.get("time")
        if timestamp is None or not isinstance(timestamp, int):
            logging.warning(f"Skipping record with invalid timestamp: {record}")
            continue
        try:
            # Push as a tuple (timestamp, counter, record) to maintain sorting
            heapq.heappush(priority_queue, (timestamp, counter, record))
            counter += 1
        except TypeError as e:
            logging.error(f"Error pushing to priority queue: {e}, record: {record}")
    logging.info(f"Finished reading file '{file_path}' for topic '{topic}'.")

# Function to send messages from the priority queue to Kafka in global timestamp order
def send_messages_from_queue(priority_queue, producer):
    while priority_queue:
        timestamp, counter, record = heapq.heappop(priority_queue)  # Ensure unpacking in the correct format
        topic = "job-events" if "task_index" not in record else "task-events"
        key = record.get("job_id", "default")
        
        # Send to Kafka with partitioning logic
        partition = timestamp % 12  # 12 partitions
        print(f"Sending record: {record}")  # Add this line
        producer.send(topic, key=key, value=record, partition=partition)
        time.sleep(0.01)
        logging.info(f"Sent event with timestamp {timestamp} to topic {topic}")
    producer.flush()

    while priority_queue:
        timestamp, record = heapq.heappop(priority_queue)
        topic = "job-events" if "task_index" not in record else "task-events"
        key = record.get("job_id", "default")
        
        # Partition events by timestamp to ensure consistency across partitions
        partition = timestamp % 12  # 12 partitions
        print(f"Sending record: {record}")  # Add this line
        producer.send(topic, key=key, value=record, partition=partition)
        time.sleep(0.01)
        logging.info(f"Sent event with timestamp {timestamp} to topic {topic}")

    producer.flush()

# Function to start streaming for all topics
# Function to start streaming for all topics
def start_streaming():
    priority_queue = []
    counter = 0  # Initialize the counter
    for topic, mapping in field_mappings.items():
        for file_path in mapping["files"]:
            stream_file_to_queue(topic, file_path, mapping["fields"], priority_queue, counter)  # Pass counter here
    send_messages_from_queue(priority_queue, producer)


if __name__ == "__main__":
    start_streaming()