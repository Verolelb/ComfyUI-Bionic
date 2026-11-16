class BionicChatPrompt:
    """Receives the prompt written by the Bionic chat panel."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "emit"
    CATEGORY = "Bionic"
    DESCRIPTION = "Prompt sent from the Bionic chat panel. The chat's RUN button fills this widget and queues the workflow."

    def emit(self, prompt):
        return (prompt,)


NODE_CLASS_MAPPINGS = {
    "BionicChatPrompt": BionicChatPrompt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BionicChatPrompt": "Bionic Chat Prompt",
}
