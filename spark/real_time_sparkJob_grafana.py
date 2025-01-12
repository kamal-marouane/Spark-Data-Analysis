import argparse
from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, to_timestamp, sum, avg, window
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, FloatType, BooleanType, LongType
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

# Argument parsing
parser = argparse.ArgumentParser(description='Spark Kafka Stream to Prometheus Pushgateway')
parser.add_argument('-PUSHGATEWAY_URL', type=str, required=True, help='Prometheus Pushgateway URL')
parser.add_argument('-KAFKA_BROKER', type=str, required=True, help='Kafka Broker URL')
args = parser.parse_args()

# Initialize Spark Session
spark = SparkSession.builder \
    .appName("Kafka Stream Task Events Job - Prometheus Pushgateway") \
    .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.1.2") \
    .getOrCreate()

# Kafka Configuration
KAFKA_BROKER = args.KAFKA_BROKER
TASK_TOPIC = "task-events"

# Prometheus Pushgateway Configuration
PUSHGATEWAY_URL = args.PUSHGATEWAY_URL

# Task Events Schema
task_events_schema = StructType([
    StructField("time", LongType(), True),
    StructField("job_id", IntegerType(), True),
    StructField("machine_id", IntegerType(), True),
    StructField("cpu_request", FloatType(), True),
    StructField("memory_request", FloatType(), True)
])

# Read from Kafka topic
task_stream = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", KAFKA_BROKER) \
    .option("subscribe", TASK_TOPIC) \
    .option("startingOffsets", "earliest") \
    .load()

# Extract and process the data
task_data = task_stream.selectExpr("CAST(value AS STRING)") \
    .select(from_json(col("value"), task_events_schema).alias("data")) \
    .select("data.*") \
    .withColumn("event_time", to_timestamp((col("time") / 1000000).cast("long")))

# Resource usage aggregation
resource_usage = task_data.groupBy(
    window(col("event_time"), "1 minute"),
    "machine_id"
).agg(
    sum("cpu_request").alias("total_cpu_usage"),
    sum("memory_request").alias("total_memory_usage")
)

# Write to Prometheus Pushgateway
def push_to_prometheus(batch_df, _):
    registry = CollectorRegistry()
    cpu_usage_gauge = Gauge('total_cpu_usage', 'Total CPU usage per machine', ['machine_id'], registry=registry)
    memory_usage_gauge = Gauge('total_memory_usage', 'Total Memory usage per machine', ['machine_id'], registry=registry)

    for row in batch_df.collect():
        cpu_usage_gauge.labels(machine_id=row.machine_id).set(float(row.total_cpu_usage))
        memory_usage_gauge.labels(machine_id=row.machine_id).set(float(row.total_memory_usage))

    push_to_gateway(PUSHGATEWAY_URL, job='spark_job_metrics', registry=registry)

# Stream to Prometheus
resource_usage.writeStream \
    .foreachBatch(push_to_prometheus) \
    .outputMode("update") \
    .start()

spark.streams.awaitAnyTermination()
