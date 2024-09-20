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

    def upload_file_to_blob(self, file_path, folder_name="invoices"):
        try:
            blob_name = f"{folder_name}/{os.path.basename(file_path)}"
            local_file = file_path
            blob_client = self.blob_service_client.get_blob_client(container=self.container_name, blob=blob_name)

            with open(file_path, "rb") as data:
                blob_client.upload_blob(data, overwrite=True)  # Overwrite the existing blob

            print(f"File {file_path} uploaded to {self.container_name}/{folder_name} successfully.")
            return local_file

        except Exception as ex:
            print(f"An error occurred during upload: {ex}")

    def AzureDocumentIntelligence(self, local_file):
        try:
            document_analysis_client = DocumentAnalysisClient(
                endpoint=endpoint, credential=AzureKeyCredential("905e186b626e4b4f99d33bdfdd47b574")
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
            return redirect(url_for('faiure'))



azure_blob_handler = AzureBlobStorageHandler(connection_string, container_name)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)
    if file and file.filename.lower().endswith('.pdf'):
        file_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(file_path)
        azure_blob_handler.delete_blob(file.filename)
        local_file = azure_blob_handler.upload_file_to_blob(file_path)
        key_value_pairs = azure_blob_handler.AzureDocumentIntelligence(local_file)
        all_key_value_pairs = {file.filename: key_value_pairs}
        excel_file = azure_blob_handler.write_to_excel(all_key_value_pairs)
        return redirect(url_for('success'))
    else:
        flash('Invalid file type. Only PDF files are allowed.')
        #return redirect(request.url)
        return redirect(url_for('failure'))
        
@app.route('/success')
def success():
    return render_template('success.html')

@app.route('/failure')
def failure():
    return render_template('failure.html')

if __name__ == '__main__':
    app.run(debug=True)
    
    

    