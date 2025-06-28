import sys

def clean_sql_file(input_file, output_file=None):
    """Removes Windows CRLF line endings and BOM from a SQL file."""
    with open(input_file, "rb") as f:
        content = f.read()

    # Remove UTF-8 BOM if present
    if content.startswith(b'\xef\xbb\xbf'):
        content = content[3:]

    # Convert CRLF (\r\n) to LF (\n)
    content = content.replace(b'\r\n', b'\n')

    # Write back to file or a new file
    output_file = output_file or input_file
    with open(output_file, "wb") as f:
        f.write(content)

    print(f"✅ Cleaned file saved as: {output_file}")

# Run from command line
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Usage: python clean_sql.py <input_file> [output_file]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    clean_sql_file(input_path, output_path)
