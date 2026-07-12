from database.session import SessionLocal
from sqlalchemy import text

with SessionLocal() as session:
    result = session.execute(
        text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'raw_document'
            ORDER BY ordinal_position
        """)
    )
    for row in result:
        print(f"{row.column_name:25s} {row.data_type:15s} nullable={row.is_nullable} default={row.column_default}")
