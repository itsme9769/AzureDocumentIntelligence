from flask import Flask, request, render_template, redirect, url_for, flash
from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient
import os
import openpyxl
import datetime
import json
from pathlib import Path
from azure.core.exceptions import ResourceNotFoundError

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Load configuration
config_path = os.path.join(os.path.dirname(__file__), 'config.json')
with open(config_path, 'r') as config_file:
    config = json.load(config_file)
connection_string = config.get("connection_string")
container_name = config.get("container_name")
endpoint = config.get("endpoint")
key = config.get("key")

# Ensure the uploads directory exists
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

class AzureBlobStorageHandler:
    def __init__(self, connection_string, container_name):
        self.connection_string = connection_string
        self.container_name = container_name
        self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
        self.container_client = self.blob_service_client.get_container_client(self.container_name)

    def delete_blob(self, blob_name):
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            container_client.delete_blob(blob_name)
            print(f"Deleted blob {blob_name} from container {self.container_name}.")
        except ResourceNotFoundError:
            print(f"Blob {blob_name} not found in container {self.container_name}.")
        except Exception as ex:
            print(f"An error occurred while deleting blob: {ex}")

    def upload_folder_to_blob(self, folder_path, folder_name="invoices"):
        uploaded_files = []
        try:
            for root, dirs, files in os.walk(folder_path):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    blob_name = f"{folder_name}/{file_name}"
                    blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)

                    with open(file_path, "rb") as data:
                        blob_client.upload_blob(data, overwrite=True)  # Overwrite existing blobs if they exist
                    print(f"File {file_path} uploaded to {self.container_name}/{folder_name} successfully.")
                    uploaded_files.append(file_path)

            return uploaded_files

        except Exception as ex:
            print(f"An error occurred during upload: {ex}")
            return None

    def AzureDocumentIntelligence(self, local_file):
        try:
            document_analysis_client = DocumentAnalysisClient(
                endpoint=endpoint, credential=AzureKeyCredential(key)
            )

            with open(local_file, "rb") as file:
                file_content = file.read()

            poller = document_analysis_client.begin_analyze_document(
                "prebuilt-document", document=file_content
            )
            result = poller.result()

            key_value_pairs = []
            for kv_pair in result.key_value_pairs:
                if kv_pair.key and kv_pair.value:
                    key = kv_pair.key.content
                    value = kv_pair.value.content if kv_pair.value else ""
                    key_value_pairs.append((key, value))

            return key_value_pairs

        except Exception as ex:
            print(f"An error occurred during document analysis: {ex}")
            return None

    def write_to_excel(self, all_key_value_pairs, excel_file=None):
        if not all_key_value_pairs:
            print("No data to write to Excel.")
            return

        if excel_file is None:
            current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            downloads_path = str(Path.home() / "Downloads")
            excel_file = os.path.join(downloads_path, f"Key_Value_Pairs_{current_time}.xlsx")

        try:
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "Key-Value Pairs"

            all_keys = set()
            for key_value_pairs in all_key_value_pairs.values():
                for key, _ in key_value_pairs:
                    all_keys.add(key)

            all_keys = sorted(all_keys)
            pdf_names = sorted(all_key_value_pairs.keys())

            headers = ["PDF Name"] + all_keys
            sheet.append(headers)

            max_lengths = {i: len(header) for i, header in enumerate(headers, start=1)}

            for pdf_name in pdf_names:
                row = [pdf_name]
                key_value_dict = {key: "" for key in all_keys}
                for key, value in all_key_value_pairs[pdf_name]:
                    key_value_dict[key] = value
                row.extend([key_value_dict[key] for key in all_keys])
                sheet.append(row)

                for i, cell in enumerate(row, start=1):
                    max_lengths[i] = max(max_lengths[i], len(str(cell)))

            for col_num, length in max_lengths.items():
                column_letter = openpyxl.utils.get_column_letter(col_num)
                sheet.column_dimensions[column_letter].width = length + 2

            workbook.save(excel_file)
            print(f"Excel file '{excel_file}' has been created successfully.")
        except Exception as ex:
            print(f"An error occurred while writing to Excel: {ex}")
            return redirect(url_for('failure'))

azure_blob_handler = AzureBlobStorageHandler(connection_string, container_name)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['GET'])
def upload():
    folder_path = request.form.get('folder_path')
    if not folder_path or not os.path.isdir(folder_path):
        flash('Invalid folder path')
        return redirect(request.url)

    uploaded_files = azure_blob_handler.upload_folder_to_blob(folder_path)
    all_key_value_pairs = {}

    for file_path in uploaded_files:
        if file_path.lower().endswith('.pdf'):
            key_value_pairs = azure_blob_handler.AzureDocumentIntelligence(file_path)
            all_key_value_pairs[os.path.basename(file_path)] = key_value_pairs

    if all_key_value_pairs:
        azure_blob_handler.write_to_excel(all_key_value_pairs)

    return redirect(url_for('success'))

@app.route('/success')
def success():
    return render_template('success.html')

if __name__ == '__main__':
    app.run(debug=True)
