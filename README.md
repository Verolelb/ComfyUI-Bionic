# ComfyUI-Bionic

[English](README.en.md) · **Français**

Un tchat façon Bionic (LM Studio) directement dans ComfyUI, avec entrée audio, entrée vision et une node réceptrice qui reçoit le prompt et lance le workflow.

## Fonctionnalités

- Panneau de chat flottant branché sur le serveur local de LM Studio (modèles texte et vision).
- Réponses en streaming, raisonnement repliable, choix du modèle dans le panneau.
- Entrée vision : bouton 🖼, collage `Ctrl+V` ou glisser-déposer d'images.
- Entrée audio : bouton 🎙, enregistrement du micro et transcription locale (faster-whisper).
- Node **Bionic Chat Prompt** : reçoit le prompt du chat et le sort en `STRING`.
- Bouton `⚡ Run` : écrit le prompt dans la node puis lance le workflow, comme le bouton Run de ComfyUI.
- Lancement automatique du workflow dès que le modèle a terminé sa réponse (actif par défaut, désactivable dans ⚙).
- Envoi automatique de la transcription audio dès l'arrêt du micro (actif par défaut, désactivable dans ⚙).
- Accès Internet : le modèle peut chercher sur le Web et ouvrir des pages pour répondre. Désactivé par défaut, activable avec le bouton 🌐 du panneau (ou dans ⚙).

## Prérequis

- ComfyUI (testé avec la version 0.45).
- [LM Studio](https://lmstudio.ai/) avec le serveur local démarré (onglet Developer → *Start server*, `http://127.0.0.1:1234`).
- Au moins un modèle de chat chargé ou téléchargé dans LM Studio.

## Installation

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Verolelb/ComfyUI-Bionic.git
```

Installe la dépendance de transcription dans le Python utilisé par ComfyUI :

```bash
# installation portable Windows
../../../python_embeded/python.exe -m pip install -r ComfyUI-Bionic/requirements.txt

# installation classique
pip install -r ComfyUI-Bionic/requirements.txt
```

Redémarre ComfyUI. Le bouton `💬 Bionic` apparaît en bas à droite de l'interface.

Le modèle Whisper `small` (~480 Mo) est téléchargé automatiquement lors de la première utilisation du micro. La taille et la langue se règlent dans ⚙.

## Utilisation

1. Ouvre le panneau avec `💬 Bionic` et choisis un modèle LM Studio.
2. Écris ton prompt, joins des images ou dicte-le avec le micro, puis envoie. À l'arrêt du micro, la transcription est envoyée automatiquement (si l'option est active) et la réponse du modèle est lancée dans le workflow.
3. Ajoute la node **Bionic Chat Prompt** (clic droit → Add Node → Bionic) et relie sa sortie `prompt` à l'entrée `text` d'un CLIP Text Encode.
4. Le prompt de la réponse est écrit dans la node et le workflow est lancé automatiquement à la fin du streaming. Le même envoi reste disponible à la main avec `⚡ Run` sous une réponse, ou `⚡ Run` dans la barre de saisie pour envoyer directement le texte tapé.

Si aucune node **Bionic Chat Prompt** n'est présente dans le graphe, elle est créée automatiquement au premier Run.

## Réglages

Le bouton ⚙ du panneau permet de modifier :

- l'URL du serveur LM Studio ;
- le prompt système ;
- la température ;
- le lancement automatique du workflow après la réponse ;
- l'envoi automatique de la transcription audio après le micro ;
- l'accès Internet (recherche web et ouverture d'URL), aussi pilotable par le bouton 🌐 à côté du micro ;
- le modèle et la langue de transcription audio.

Les réglages sont enregistrés dans `bionic_chat/config.json`, dans le dossier `user` de ComfyUI.

## Fonctionnement

- `nodes.py` : node `BionicChatPrompt` (sortie `STRING`).
- `bionic_server.py` : routes `/bionic_chat/config`, `/bionic_chat/chat` (proxy streaming vers LM Studio) et `/bionic_chat/transcribe` (Whisper local).
- `web/bionic_chat.js` et `web/bionic_chat.css` : panneau de chat, enregistrement audio, pièces jointes et déclenchement du workflow.
- Outils web : `web_search` (Bing, sans clé, avec repli DuckDuckGo) et `open_url` (lecture de page), exécutés par le serveur dans une boucle d'appels d'outils LM Studio (3 tours, puis réponse forcée en texte). Les adresses locales et privées sont refusées.

## Limites

- La transcription est effectuée après l'arrêt de l'enregistrement (pas de transcription mot-à-mot en temps réel).
- La transcription tourne sur le CPU en `int8`.
- L'historique de conversation n'est pas conservé entre deux rechargements de la page.
