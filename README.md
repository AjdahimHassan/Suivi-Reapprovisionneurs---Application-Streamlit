# 📦 Suivi Réapprovisionneurs — Application Streamlit

Application de suivi quotidien des passages en salle des réapprovisionneurs.

## 🚀 Lancement local

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Lancer l'application
streamlit run app.py
```

L'application s'ouvre automatiquement sur http://localhost:8501

---

## ☁️ Déploiement sur Streamlit Cloud (gratuit)

1. **Pusher ce dossier sur GitHub** (repo public ou privé)
2. Aller sur [share.streamlit.io](https://share.streamlit.io)
3. Connecter votre compte GitHub
4. Cliquer **"New app"** → sélectionner le repo et le fichier `app.py`
5. Cliquer **"Deploy"** → l'app est en ligne en 2 minutes

---

## 🖥️ Déploiement sur un serveur (VPS, Docker)

### Avec Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

```bash
docker build -t suivi-reappro .
docker run -p 8501:8501 suivi-reappro
```

### Sans Docker

```bash
pip install -r requirements.txt
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

---

## 📁 Structure des fichiers

```
suivi_reappro_streamlit/
├── app.py                  # Application principale Streamlit
├── planning_parser.py      # Parsing des fichiers planning CSV
├── chargement_parser.py    # Parsing du fichier chargement machine
├── excel_export.py         # Génération du fichier Excel
├── requirements.txt        # Dépendances Python
└── README.md
```

---

## 📂 Format des fichiers CSV

### Planning (un fichier par réappro, nom du fichier = nom du réappro)

| semaine | jour    | client     | machine  |
|---------|---------|------------|----------|
| S1      | Lundi   | Casino ABC | M001     |
| S1      | Lundi   | Carrefour  | M002     |
| S2      | Lundi   | Leclerc    | M003     |

> Le script garde automatiquement la semaine avec le plus de salles.

### Chargement machine (un fichier par jour)

| employe | machine | statut | montant |
|---------|---------|--------|---------|
| RIDF1   | M001    | Fait   | 150.50  |
| RIDF2   | M005    | Fait   | -20.00  |
| RIDF1   | M002    | Fait   | 0       |  ← NON compté (valeur = 0)

---

## 🎨 Code couleur

| Couleur | Signification |
|---------|---------------|
| 🟢 Vert | Salle faite normalement |
| 🔴 Rouge | Salle non faite |
| 🟡 Orange | Joker (faite par un autre réappro) |
