import os
from typing import Any, List
from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool

# Load environment variables from the specific path
load_dotenv(dotenv_path='./.env')

# Initialize the Connection Pool
# Min 1 connection, Max 10 connections (adjust as needed for your application)
connection_pool = psycopg2.pool.SimpleConnectionPool(
    1, 
    10,
    user=os.getenv("PG_USER"),
    host=os.getenv("PG_HOST"),
    database=os.getenv("PG_DATABASE"),
    password=os.getenv("PG_PASSWORD"),
    port=int(os.getenv("PG_PORT", 5432)) # Defaults to 5432 if not provided
)

def query(text: str, params: List[Any] = None) -> List[dict]:
    """
    Executes a SQL query using a connection from the pool.
    Returns the rows as a list of dictionaries (similar to pg in JS).
    """
    # print(f"SQL: {text}")
    # print(f"Params: {params}")
    
    conn = None
    try:
        # Get a connection from the pool
        conn = connection_pool.getconn()
        
        # Using RealDictCursor allows fetching rows as key-value pairs (dictionaries)
        # instead of standard tuples, matching Node.js behavior.
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(text, params or [])
            
            # Commit the transaction if it modifies data (INSERT/UPDATE/DELETE)
            conn.commit()
            
            # Try to fetch results if the query returns rows (e.g., SELECT)
            try:
                return cursor.fetchall()
            except psycopg2.ProgrammingError:
                # No results to fetch (e.g., successful UPDATE or INSERT without RETURNING)
                return []
                
    except Exception as error:
        if conn:
            conn.rollback()
        raise error
        
    finally:
        # Crucial: Always return the connection back to the pool
        if conn:
            connection_pool.putconn(conn)

# Optional cleanup function to call when your app shuts down
def close_pool():
    if connection_pool:
        connection_pool.closeall()