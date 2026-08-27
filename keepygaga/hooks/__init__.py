"""Built-in, host-adapted Keepygaga hook runtime."""

from keepygaga.hooks.fragments import build_fragment
from keepygaga.hooks.merge import HookFragmentError, merge_hook_fragment

__all__ = ["HookFragmentError", "build_fragment", "merge_hook_fragment"]
