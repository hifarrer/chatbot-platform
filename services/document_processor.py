import os
import PyPDF2
import docx
from pathlib import Path

class DocumentProcessor:
    def __init__(self):
        pass
    
    def process_document(self, file_path):
        """
        Process a document and extract text based on file type
        """
        print(f"📄 DEBUG: Processing document: {file_path}")
        
        file_extension = Path(file_path).suffix.lower()
        print(f"🔍 DEBUG: File extension: {file_extension}")
        
        if file_extension == '.pdf':
            text = self._process_pdf(file_path)
        elif file_extension == '.docx':
            text = self._process_docx(file_path)
        elif file_extension == '.txt':
            text = self._process_txt(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_extension}")
        
        print(f"✅ DEBUG: Extracted {len(text)} characters from document")
        print(f"📝 DEBUG: First 200 characters: {text[:200]}...")
        
        return text
    
    def _process_pdf(self, file_path):
        """Extract text from PDF file"""
        text = ""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                print(f"📖 DEBUG: PDF has {len(pdf_reader.pages)} pages")
                
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    text += page_text + "\n"
                    print(f"   Page {page_num + 1}: {len(page_text)} characters")
                    
        except Exception as e:
            raise Exception(f"Error processing PDF: {str(e)}")
        
        return text.strip()
    
    def _process_docx(self, file_path):
        """Extract text from DOCX file"""
        text = ""
        try:
            doc = docx.Document(file_path)
            print(f"📖 DEBUG: DOCX has {len(doc.paragraphs)} paragraphs")
            
            for i, paragraph in enumerate(doc.paragraphs):
                paragraph_text = paragraph.text
                text += paragraph_text + "\n"
                if i < 5:  # Show first 5 paragraphs
                    print(f"   Paragraph {i + 1}: {paragraph_text[:100]}...")
                    
        except Exception as e:
            raise Exception(f"Error processing DOCX: {str(e)}")
        
        return text.strip()
    
    def _process_txt(self, file_path):
        """Extract text from TXT file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                text = file.read()
                print(f"📖 DEBUG: TXT file read successfully")
        except UnicodeDecodeError:
            # Try with different encoding if UTF-8 fails
            try:
                with open(file_path, 'r', encoding='latin-1') as file:
                    text = file.read()
                    print(f"📖 DEBUG: TXT file read with latin-1 encoding")
            except Exception as e:
                raise Exception(f"Error processing TXT file: {str(e)}")
        except Exception as e:
            raise Exception(f"Error processing TXT file: {str(e)}")
        
        return text.strip()
    
    def chunk_text(self, text, chunk_size=1000, overlap=100):
        """
        Split text into chunks for better processing
        """
        words = text.split()
        chunks = []
        
        for i in range(0, len(words), chunk_size - overlap):
            chunk = ' '.join(words[i:i + chunk_size])
            chunks.append(chunk)
            
            if i + chunk_size >= len(words):
                break
        
        print(f"🔢 DEBUG: Split text into {len(chunks)} chunks")
        return chunks 