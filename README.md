# Dia 1 MVP - RENIEC verifica acta
Busca sem DNI. Emissão com DNI S/10,30 cód 02141.

Rodar:
pip install -r requirements.txt
uvicorn app:app --port 8901
Abrir http://127.0.0.1:8901

Teste ok 03/10/2026: 03/MENDOZA/ESTEBAN/GREGORIA/1981 = UBICADA via API.
Limites: 1 consulta/job, delay 2.5s, uso familiar, Ley 29733.
Faixa 30 dias entra Dia 2.
