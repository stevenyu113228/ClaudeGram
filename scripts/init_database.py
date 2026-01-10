#!/usr/bin/env python3
"""Script to initialize or reset the database."""
import argparse
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from common.database import S3SQLiteManager, UserRepository


def main():
    parser = argparse.ArgumentParser(description="Initialize bot database")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--key", default="chatbot.db", help="Database key in S3")
    parser.add_argument(
        "--add-user",
        type=int,
        help="Add initial admin user with this Telegram user ID",
    )
    parser.add_argument("--username", help="Username for the initial user")
    parser.add_argument("--display-name", help="Display name for the initial user")

    args = parser.parse_args()

    # Initialize database
    print(f"Initializing database at s3://{args.bucket}/{args.key}")
    db = S3SQLiteManager(bucket=args.bucket, key=args.key)

    # This will create the database and upload to S3
    with db.connection() as conn:
        # Database is automatically initialized with schema
        print("Database schema created/verified")

        # Check tables
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Tables: {', '.join(tables)}")

    # Add initial user if specified
    if args.add_user:
        user_repo = UserRepository(db)
        user = user_repo.add_user(
            telegram_user_id=args.add_user,
            username=args.username,
            display_name=args.display_name,
            added_by="init_script",
        )
        print(f"Added user: {user}")

    print("Database initialization complete!")


if __name__ == "__main__":
    main()
