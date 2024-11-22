import os
import io
import openai
import logging
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
import PyPDF2
import docx

# Configuration de l'API OpenAI
openai.api_key = 'your-openai-api-key'

# Configuration des scopes pour Google Drive
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# Configuration des logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

def authenticate_google_drive():
    """Authentifie l'utilisateur et retourne le service Google Drive."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('drive', 'v3', credentials=creds)

def retrieve_context(question, search_type):
    """Recherche dans Google Drive des fichiers correspondant à la question."""
    drive_service = authenticate_google_drive()
    query = f"name contains '{question}'"  # Recherche par nom de fichier
    logger.info(f"Requête Drive: {query}")
    
    try:
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        # Si aucun fichier trouvé, on peut aussi chercher par type de fichier
        if not files:
            logger.warning(f"Aucun fichier trouvé pour la requête: {question}")
            return []
        
        # Retourne les fichiers trouvés
        logger.info(f"Fichiers trouvés: {[file['name'] for file in files]}")
        return files
    except HttpError as error:
        logger.error(f"Une erreur est survenue lors de la recherche: {error}")
        return []

def extract_text_from_pdf(file):
    """Extrait le texte d'un fichier PDF."""
    pdf_reader = PyPDF2.PdfReader(file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    return text

def extract_text_from_docx(file):
    """Extrait le texte d'un fichier Word (.docx)."""
    doc = docx.Document(file)
    text = ""
    for para in doc.paragraphs:
        text += para.text + "\n"
    return text

def read_file_content(service, file_id):
    """Lit le contenu d'un fichier depuis Google Drive (PDF, DOCX, TXT)."""
    try:
        file = service.files().get(fileId=file_id).execute()
        file_name = file['name']
        
        # Télécharger le fichier depuis Google Drive
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        fh.seek(0)

        # Vérifie le type de fichier et utilise l'extracteur approprié
        if file_name.endswith('.txt'):
            content = fh.read().decode('utf-8')
        elif file_name.endswith('.pdf'):
            content = extract_text_from_pdf(fh)
        elif file_name.endswith('.docx'):
            content = extract_text_from_docx(fh)
        else:
            logger.warning(f"Le fichier {file_name} n'est pas pris en charge pour l'extraction de texte.")
            return None
        
        return content
    except HttpError as error:
        logger.error(f"Une erreur est survenue lors de la lecture du fichier: {error}")
        return None

def generate_response_with_rag(question, search_type):
    """Génère une réponse basée sur la recherche dans Google Drive et l'IA."""
    # Recherche le fichier correspondant
    files = retrieve_context(question, search_type)
    if not files:
        return "Désolé, je n'ai pas trouvé de fichier pertinent."
    
    # Récupère l'ID du fichier trouvé
    file_id = files[0]['id']
    
    # Lecture du contenu du fichier
    content = read_file_content(authenticate_google_drive(), file_id)
    
    if not content:
        return "Le contenu du fichier est vide ou inaccessible."
    
    # Crée un prompt en utilisant le contenu du fichier trouvé
    full_prompt = f"Voici le contenu trouvé dans le fichier : {content}\n\nQuestion : {question}\nRéponse :"
    
    try:
        # Envoie le prompt au modèle de génération de réponse
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{'role': 'user', 'content': full_prompt}],
            temperature=0.7  # Ajuste la créativité du modèle si nécessaire
        )
        return response['choices'][0]['message']['content']
    except openai.error.OpenAIError as e:
        logger.error(f"Erreur avec l'API OpenAI : {e}")
        return "Une erreur est survenue lors de la génération de la réponse."
