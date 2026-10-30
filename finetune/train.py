"""QLoRA fine-tune of a chat model on provenum anchoring examples.

Loss is computed on the assistant reply only (the JSON path), not on the prompt. Everything
needed to reproduce the run is written to OUT: config.json (arguments and library versions),
the trainer's log history (log_history.json), checkpoints and the final adapter (adapter/).

Usage:
    python train.py --data data --out runs/qwen3-32b-r16 [--epochs 1] [--rank 16]
"""

import argparse
import json
import platform
from pathlib import Path


def main() -> None:
    """Train a LoRA adapter and save it with its config and logs."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, required=True, help="directory with train/val.jsonl")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base", default="unsloth/Qwen3-32B-unsloth-bnb-4bit")
    parser.add_argument("--max-len", type=int, default=8192)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--accum", type=int, default=8)
    parser.add_argument("--max-train", type=int, help="use only the first N training examples")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    # unsloth must be imported before transformers/trl so its patches apply.
    from unsloth import FastLanguageModel  # noqa: I001 - must load before transformers and trl
    from unsloth.chat_templates import train_on_responses_only

    import torch
    import transformers
    import trl
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer

    args.out.mkdir(parents=True, exist_ok=True)
    config = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    config["versions"] = {"python": platform.python_version(), "torch": torch.__version__,
                          "transformers": transformers.__version__, "trl": trl.__version__,
                          "gpu": torch.cuda.get_device_name(0)}  # fmt: skip
    (args.out / "config.json").write_text(json.dumps(config, indent=1), encoding="utf-8")

    model, tokenizer = FastLanguageModel.from_pretrained(
        args.base, max_seq_length=args.max_len, load_in_4bit=True
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=0,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        use_gradient_checkpointing="unsloth",
        random_state=args.seed,
    )

    def render(example: dict) -> dict:
        """
        Render one example with the model's chat template (thinking off, as at inference).

        Args:
            example (dict): {messages, meta}.

        Returns:
            dict: {"text": rendered conversation}.
        """
        text = tokenizer.apply_chat_template(
            example["messages"], tokenize=False, enable_thinking=False
        )
        return {"text": text}

    files = {"train": str(args.data / "train.jsonl"), "val": str(args.data / "val.jsonl")}
    data = load_dataset("json", data_files=files)
    if args.max_train:
        data["train"] = data["train"].select(range(min(args.max_train, len(data["train"]))))
    data = data.map(render, remove_columns=["messages", "meta"])

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,  # TRL >= 0.12 name for the tokenizer
        train_dataset=data["train"],
        eval_dataset=data["val"],
        args=SFTConfig(
            output_dir=str(args.out / "checkpoints"),
            dataset_text_field="text",
            max_length=args.max_len,  # TRL >= 0.20 name for max_seq_length
            per_device_train_batch_size=args.batch,
            per_device_eval_batch_size=args.batch,
            gradient_accumulation_steps=args.accum,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            lr_scheduler_type="cosine",
            warmup_ratio=0.03,
            optim="adamw_8bit",
            bf16=True,
            logging_steps=10,
            eval_strategy="steps",
            eval_steps=100,
            save_steps=200,
            save_total_limit=3,
            seed=args.seed,
            report_to="none",
        ),
    )
    trainer = train_on_responses_only(
        trainer,
        instruction_part="<|im_start|>user\n",
        response_part="<|im_start|>assistant\n",
    )
    result = trainer.train()
    model.save_pretrained(str(args.out / "adapter"))
    tokenizer.save_pretrained(str(args.out / "adapter"))
    (args.out / "log_history.json").write_text(
        json.dumps(trainer.state.log_history, indent=1), encoding="utf-8"
    )
    (args.out / "train_result.json").write_text(json.dumps(result.metrics, indent=1),
                                                encoding="utf-8")  # fmt: skip
    print(json.dumps(result.metrics, indent=1))


if __name__ == "__main__":
    main()
