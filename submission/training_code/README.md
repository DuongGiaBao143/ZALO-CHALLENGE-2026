# Training code

**No training, fine-tuning, distillation or synthetic-data generation was performed for this submission.**

The model is the unmodified public Ornith 1.5 9B checkpoint (MIT licence), run as the
Ollama GGUF build `ornith-1.5:9b` (Q4_K_M). The only change is a Modelfile overlay
(`ornith15-datamate-pilot-8k`) that sets inference parameters (context length, seed, batch size).
No public or private test data was used for anything.

* `data_manifest.json` lists the packaged model files with SHA-256 checksums and states
  that the training/validation sample counts are zero.
* The agent code, prompts and tool definitions live in `/code/runtime` and `/code/inference`.
