from sqlalchemy import text

from database.session import engine


def test_connection():
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version();")).scalar()

            print("======================================")
            print("✅ Database connection successful!")
            print("======================================")
            print(version)

    except Exception as e:
        print("======================================")
        print("❌ Database connection failed!")
        print("======================================")
        print(e)


if __name__ == "__main__":
    test_connection()
