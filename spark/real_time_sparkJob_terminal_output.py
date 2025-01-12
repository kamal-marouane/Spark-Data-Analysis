from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, to_timestamp, sum, avg, count, window
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, FloatType, BooleanType, LongType

# Initialize Spark Session
spark = SparkSession.builder \
    .appName("Kafka Stream Job - Resource and Event Processing") \
    .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.1.2") \
    .getOrCreate()

# Kafka broker and topic configuration
KAFKA_BROKER = "34.45.123.229:9094"
TASK_TOPIC = "task-events"
JOB_TOPIC = "job-events"

# Task Events Schema
task_events_schema = StructType([
    StructField("time", LongType(), True),
    StructField("missing_info", IntegerType(), True),
    StructField("job_id", IntegerType(), True),
    StructField("task_index", IntegerType(), True),
    StructField("machine_id", IntegerType(), True),
    StructField("event_type", IntegerType(), True),
    StructField("user", StringType(), True),
    StructField("scheduling_class", IntegerType(), True),
    StructField("priority", IntegerType(), True),
    StructField("cpu_request", FloatType(), True),
    StructField("memory_request", FloatType(), True),
    StructField("disk_space_request", FloatType(), True),
    StructField("different_machines_restriction", BooleanType(), True)
])

# Job Events Schema
job_events_schema = StructType([
    StructField("time", LongType(), True),
    StructField("missing_info", IntegerType(), True),
    StructField("job_id", IntegerType(), True),
    StructField("event_type", IntegerType(), True),
    StructField("user", StringType(), True),
    StructField("scheduling_class", IntegerType(), True),
    StructField("job_name", StringType(), True),
    StructField("logical_job_name", StringType(), True)
])

# --- TASK EVENTS STREAM ---

# Read from task-events topic
task_stream = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", KAFKA_BROKER) \
    .option("subscribe", TASK_TOPIC) \
    .option("startingOffsets", "earliest") \
    .load()

# Deserialize JSON and extract fields
task_data = task_stream.selectExpr("CAST(value AS STRING)") \
    .select(from_json(col("value"), task_events_schema).alias("data")) \
    .select("data.*") \
    .withColumn("event_time", to_timestamp((col("time") / 1000000).cast("long")))

# Add a watermark to define lateness threshold
task_data_with_watermark = task_data.withWatermark("event_time", "5 minutes")

# Calculate CPU and Memory usage over a 5-minute sliding window
resource_usage = task_data_with_watermark.groupBy(
    window(col("event_time"), "5 minutes", "1 minute"),
    "machine_id"
).agg(
    sum("cpu_request").alias("total_cpu_usage"),
    sum("memory_request").alias("total_memory_usage"),
    avg("cpu_request").alias("avg_cpu_request_per_task"),
    avg("memory_request").alias("avg_memory_request_per_task")
).select(
    col("window.start").alias("window_start"),
    col("window.end").alias("window_end"),
    "machine_id",
    "total_cpu_usage",
    "total_memory_usage",
    "avg_cpu_request_per_task",
    "avg_memory_request_per_task"
)

# --- JOB EVENTS STREAM ---

# Read from job-events topic
job_stream = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", KAFKA_BROKER) \
    .option("subscribe", JOB_TOPIC) \
    .option("startingOffsets", "earliest") \
    .load()

# Deserialize JSON and extract fields
job_data = job_stream.selectExpr("CAST(value AS STRING)") \
    .select(from_json(col("value"), job_events_schema).alias("data")) \
    .select("data.*") \
    .withColumn("event_time", to_timestamp((col("time") / 1000000).cast("long")))

# Add a watermark to define lateness threshold
job_data_with_watermark = job_data.withWatermark("event_time", "5 minutes")

# Count events per user and event type in a 5-minute window
event_count_per_user = job_data_with_watermark.groupBy(
    window(col("event_time"), "5 minutes", "1 minute"),
    "user",
    "event_type"
).agg(
    count("*").alias("event_count")
).select(
    col("window.start").alias("window_start"),
    col("window.end").alias("window_end"),
    "user",
    "event_type",
    "event_count"
)

# --- Separate Console Outputs ---

# Console output for resource usage (task-events)
resource_usage.writeStream \
    .outputMode("update") \
    .format("console") \
    .option("truncate", False) \
    .start()

# Console output for event count per user (job-events)
event_count_per_user.writeStream \
    .outputMode("update") \
    .format("console") \
    .option("truncate", False) \
    .start()

# Start streaming
spark.streams.awaitAnyTermination()