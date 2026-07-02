import psycopg2

def create_postgresql_database():
    # 1. Define connection details to the default 'postgres' database
    host = "localhost"
    port = "5432"
    user = "postgres"
    password = "Soravic2202!"  # Replace with your actual password
    default_db = "postgres"     # Connect to default system DB first
    
    new_db_name = "dmscheduler"

    try:
        # 2. Establish connection to the server
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=default_db
        )
        
        # CRITICAL: Enable autocommit to run CREATE DATABASE outside a transaction
        conn.autocommit = True
        
        # 3. Create a cursor object
        cursor = conn.cursor()
        
        # 4. Check if the database already exists to prevent errors
        cursor.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{new_db_name}';")
        exists = cursor.fetchone()
        
        if not exists:
            # 5. Execute the creation query
            cursor.execute(f"CREATE DATABASE {new_db_name};")
            print(f"Database '{new_db_name}' created successfully!")
        else:
            print(f"Database '{new_db_name}' already exists.")
            
    except Exception as e:
        print(f"An error occurred: {e}")
        
    finally:
        # 6. Clean up and close connections
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    create_postgresql_database()