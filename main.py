import os
import logging
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import PyPDF2
from docx import Document
import ollama
import io

# Configuration du logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Fonction d'authentification Google Drive
def authenticate_google_drive():
    """Authentifie et retourne le service Google Drive"""
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
    creds = None
    
    try:
        if os.path.exists('token.json'):
            logger.info("Chargement du token existant")
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Rafraîchissement du token expiré")
                creds.refresh(Request())
            else:
                logger.info("Génération d'un nouveau token")
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
                logger.info("Nouveau token sauvegardé")
                
        return build('drive', 'v3', credentials=creds)
    
    except Exception as e:
        logger.error(f"Erreur d'authentification: {str(e)}")
        raise

# Fonction pour rechercher les fichiers dans Google Drive
def get_drive_documents(query):
    """Récupère les fichiers de Google Drive en fonction de la requête"""
    try:
        service = authenticate_google_drive()
        
        mime_types = [
            'text/plain',             # TXT
            'application/pdf',        # PDF
            'application/msword',     # DOC
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # DOCX
            'application/vnd.ms-excel',  # XLS
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # XLSX
            'text/csv'               # CSV
        ]
        
        query = query.replace("'", "\\'")  # Protéger les apostrophes dans la requête
        query_string = f"name contains '{query}'"
        
        logger.info(f"Requête Drive: {query_string}")
        
        # Recherche dans les fichiers Drive
        mime_query = f"({' or '.join([f"mimeType='{mime}'" for mime in mime_types])})"
        full_query = f"{query_string} and {mime_query}"
        
        results = service.files().list(
            q=full_query,
            fields="files(name, id, mimeType)"
        ).execute()
        
        files = results.get('files', [])
        
        if not files:
            logger.warning(f"Aucun fichier trouvé pour la requête: {query}")
        else:
            logger.info(f"Fichiers trouvés: {[f['name'] for f in files]}")

        return [{'name': file['name'], 'id': file['id'], 'mimeType': file['mimeType']} for file in files]
        
    except Exception as e:
        logger.error(f"Erreur lors de la recherche Drive: {str(e)}")
        return []

# Fonction pour extraire le texte d'un fichier PDF
def extract_text_from_pdf(file_id, service):
    """Extrait le texte d'un fichier PDF sur Google Drive"""
    request = service.files().get_media(fileId=file_id)
    file = request.execute()
    
    pdf_file = PyPDF2.PdfReader(io.BytesIO(file))
    text = ""
    for page in pdf_file.pages:
        text += page.extract_text()
    
    return text

# Fonction pour extraire le texte d'un fichier DOCX
def extract_text_from_docx(file_id, service):
    """Extrait le texte d'un fichier DOCX sur Google Drive"""
    request = service.files().get_media(fileId=file_id)
    file = request.execute()
    
    doc = Document(io.BytesIO(file))
    text = ""
    for para in doc.paragraphs:
        text += para.text + "\n"
    
    return text

# Fonction pour extraire le texte d'un fichier TXT
def extract_text_from_txt(file_id, service):
    """Extrait le texte d'un fichier TXT sur Google Drive"""
    try:
        request = service.files().get_media(fileId=file_id)
        file = request.execute()
        text = file.decode('utf-8')  # Décodage du contenu du fichier TXT en texte
        return text
    except Exception as e:
        logger.error(f"Erreur d'extraction TXT: {str(e)}")
        return ""

# Fonction pour récupérer le contenu des fichiers trouvés
def retrieve_file_content(files):
    """Récupère le contenu des fichiers trouvés (PDF, DOCX, TXT)"""
    service = authenticate_google_drive()
    context = []
    
    for file in files:
        file_id = file['id']
        mime_type = file['mimeType']
        
        if mime_type == 'application/pdf':
            text = extract_text_from_pdf(file_id, service)
            context.append(f"[PDF] {file['name']} : {text[:500]}...")  # Limite le texte à 500 premiers caractères
        elif mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
            text = extract_text_from_docx(file_id, service)
            context.append(f"[DOCX] {file['name']} : {text[:500]}...")  # Limite le texte à 500 premiers caractères
        elif mime_type == 'text/plain':  # Ajouter la gestion des fichiers .txt
            text = extract_text_from_txt(file_id, service)
            context.append(f"[TXT] {file['name']} : {text[:500]}...")  # Limite le texte à 500 premiers caractères
        else:
            logger.info(f"Fichier de type non pris en charge : {file['name']} ({mime_type})")
    
    return context

# Fonction de recherche sur Google pour compléter la réponse
def search_google(query):
    """Effectue une recherche Google et retourne les résultats"""
    API_KEY = "AIzaSyACo927KZ6zkUZn2zbMJNd1mEHvFFAUFxQ"
    SEARCH_ENGINE_ID = "669cb7720de434b79"
    
    url = f"https://www.googleapis.com/customsearch/v1"
    params = {
        'key': API_KEY,
        'cx': SEARCH_ENGINE_ID,
        'q': query
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        results = response.json().get('items', [])
        return [item['snippet'] for item in results[:3]]
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de la recherche Google: {str(e)}")
        return []

# Fonction pour générer la réponse basée sur le contexte
def generate_response_with_rag(question, search_type='drive'):
    """Génère une réponse basée sur le contexte récupéré"""
    try:
        # Récupération des fichiers depuis Google Drive
        drive_docs = get_drive_documents(question)
        context_docs = []
        
        if drive_docs:
            context_docs.extend(retrieve_file_content(drive_docs))
        
        # Si aucune réponse n'est trouvée sur Drive, on cherche sur le web
        if not context_docs and search_type in ['web', 'all']:
            web_results = search_google(question)
            context_docs.extend([f"[Web] {result}" for result in web_results])
        
        if not context_docs:
            return "Désolé, je n'ai trouvé aucun document pertinent pour votre question."
        
        context = "\n".join(context_docs)
        full_prompt = f"Contextes pertinents :\n{context}\n\nQuestion : {question}\n\nRéponse :"
        
        # Envoi à Ollama pour générer une réponse
        response = ollama.chat(
            model="llama3.2",  # Assurez-vous que vous avez accès au modèle Llama
            messages=[{'role': 'user', 'content': full_prompt}]
        )
        
        return response['message']['content']
    
    except Exception as e:
        logger.error(f"Erreur lors de la génération de la réponse: {str(e)}")
        return f"Une erreur s'est produite: {str(e)}"

# Fonction principale
def main():
    print("Chat RAG - Recherche flexible")
    print("Types de recherche : drive, web, all")
    print("Tapez 'exit' pour quitter")
    
    while True:
        try:
            search_type = input("\nType de recherche (drive/web/all) : ").lower()
            if search_type == 'exit':
                break
            
            if search_type not in ['drive', 'web', 'all']:
                print("Type de recherche invalide. Utilisez 'drive', 'web' ou 'all'")
                continue
            
            question = input("Votre question : ")
            if question.lower() == 'exit':
                break
            
            print("\nRecherche en cours...")
            response = generate_response_with_rag(question, search_type)
            print(f"\nRéponse RAG : {response}")
        
        except Exception as e:
            logger.error(f"Erreur dans la boucle principale: {str(e)}")

if __name__ == "__main__":
    main()
