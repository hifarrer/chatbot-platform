-- PostgreSQL INSERT statements generated on 2025-09-21 22:21:56.547678
-- This file contains all data from the PostgreSQL database

-- Users
-- =====
INSERT INTO "user" (id, username, email, password_hash, created_at) VALUES (2, 'admin', 'admin@chatbot-platform.com', 'scrypt:32768:8:1$ZALTzhBnIN5kpxWV$0e0505d94e1eba92b1dda953a03417c3e4c02e96069e3aad85b21298d1076e06cb0ba89defa32f55e183580ea15771710faf05f47000f14c9d56beca2d2393d8', '2025-09-22T03:21:40.884048');
INSERT INTO "user" (id, username, email, password_hash, created_at) VALUES (3, 'demo_user', 'demo@example.com', 'scrypt:32768:8:1$ZALTzhBnIN5kpxWV$0e0505d94e1eba92b1dda953a03417c3e4c02e96069e3aad85b21298d1076e06cb0ba89defa32f55e183580ea15771710faf05f47000f14c9d56beca2d2393d8', '2025-09-22T03:21:40.884048');
INSERT INTO "user" (id, username, email, password_hash, created_at) VALUES (4, 'john_doe', 'john@example.com', 'scrypt:32768:8:1$ZALTzhBnIN5kpxWV$0e0505d94e1eba92b1dda953a03417c3e4c02e96069e3aad85b21298d1076e06cb0ba89defa32f55e183580ea15771710faf05f47000f14c9d56beca2d2393d8', '2025-09-22T03:21:40.884048');

-- Chatbots
-- =========
INSERT INTO chatbot (id, name, description, system_prompt, embed_code, user_id, created_at, is_trained) VALUES (2, 'Platform Assistant', 'A helpful assistant for owlbee.ai', 'You are the Platform Assistant for owlbee.ai. You are knowledgeable, friendly, and enthusiastic about helping users understand how to create and deploy AI chatbots.', 'a80eb9ae-21cb-4b87-bfa4-2b3a0ec6cafb', 2, '2025-09-22T03:21:40.884048', true);
INSERT INTO chatbot (id, name, description, system_prompt, embed_code, user_id, created_at, is_trained) VALUES (3, 'Customer Support Bot', 'Handles customer support inquiries', 'You are a customer support assistant. Help users with their questions and provide friendly, professional assistance.', 'b91fc8bf-32dc-5c98-cgb5-3c4b1fd7dafc', 3, '2025-09-22T03:21:40.884048', true);
INSERT INTO chatbot (id, name, description, system_prompt, embed_code, user_id, created_at, is_trained) VALUES (4, 'FAQ Bot', 'Answers frequently asked questions', 'You are an FAQ assistant. Provide clear and concise answers to common questions.', 'c02gd9cg-43ed-6da9-dhc6-4d5c2ge8ebgd', 4, '2025-09-22T03:21:40.884048', false);

-- Documents
-- =========
INSERT INTO document (id, filename, original_filename, file_path, chatbot_id, uploaded_at, processed) VALUES (1, 'platform_guide.pdf', 'Platform Guide.pdf', '/uploads/platform_guide.pdf', 2, '2025-09-22T03:21:40.884048', true);
INSERT INTO document (id, filename, original_filename, file_path, chatbot_id, uploaded_at, processed) VALUES (2, 'support_manual.pdf', 'Support Manual.pdf', '/uploads/support_manual.pdf', 3, '2025-09-22T03:21:40.884048', true);
INSERT INTO document (id, filename, original_filename, file_path, chatbot_id, uploaded_at, processed) VALUES (3, 'faq_document.txt', 'FAQ Document.txt', '/uploads/faq_document.txt', 4, '2025-09-22T03:21:40.884048', false);

-- Conversations
-- =============
INSERT INTO conversation (id, chatbot_id, user_message, bot_response, timestamp) VALUES (1, 2, 'Hello!', 'Hi there! I''m the Platform Assistant. How can I help you today?', '2025-09-22T03:21:40.884048');
INSERT INTO conversation (id, chatbot_id, user_message, bot_response, timestamp) VALUES (2, 2, 'How do I create a chatbot?', 'To create a chatbot, go to your dashboard and click "Create Chatbot". Give it a name, description, and upload training documents.', '2025-09-22T03:21:40.884048');
INSERT INTO conversation (id, chatbot_id, user_message, bot_response, timestamp) VALUES (3, 3, 'I need help with my account', 'I''d be happy to help you with your account. What specific issue are you experiencing?', '2025-09-22T03:21:40.884048');
INSERT INTO conversation (id, chatbot_id, user_message, bot_response, timestamp) VALUES (4, 3, 'How do I reset my password?', 'You can reset your password by clicking the "Forgot Password" link on the login page.', '2025-09-22T03:21:40.884048');
INSERT INTO conversation (id, chatbot_id, user_message, bot_response, timestamp) VALUES (5, 4, 'What are your business hours?', 'Our business hours are Monday through Friday, 9 AM to 5 PM EST.', '2025-09-22T03:21:40.884048');
INSERT INTO conversation (id, chatbot_id, user_message, bot_response, timestamp) VALUES (6, 4, 'Do you offer refunds?', 'Yes, we offer a 30-day money-back guarantee for all our services.', '2025-09-22T03:21:40.884048');

-- Settings
-- ========
INSERT INTO settings (id, key, value, updated_at) VALUES (1, 'homepage_chatbot_id', '2', '2025-09-22T03:21:40.884048');
INSERT INTO settings (id, key, value, updated_at) VALUES (2, 'homepage_chatbot_title', 'Platform Assistant', '2025-09-22T03:21:40.884048');
INSERT INTO settings (id, key, value, updated_at) VALUES (3, 'homepage_chatbot_placeholder', 'Ask me anything about the platform...', '2025-09-22T03:21:40.884048');
INSERT INTO settings (id, key, value, updated_at) VALUES (4, 'max_file_size', '16777216', '2025-09-22T03:21:40.884048');
INSERT INTO settings (id, key, value, updated_at) VALUES (5, 'allowed_file_types', 'pdf,docx,txt', '2025-09-22T03:21:40.884048');
