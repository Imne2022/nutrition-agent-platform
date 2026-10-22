from sqlalchemy import create_engine, text

from backend.app.config import DATABASE_URL

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is missing from the project .env file"
    )

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


def check_database() -> bool:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


if __name__ == "__main__":
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT current_database()")
        )
        print("Connected database:", result.scalar())