"""
Prompt Loader Utility for Agents Evo

Loads external prompt files with a flexible naming scheme that supports
multiple variants and biases for each agent role.

Naming convention: {agent_name}.{bias_specialty}.{variant_id}.prompt.md

Example: market_analyst.technical.v1.prompt.md
         bull_researcher.aggressive.v2.prompt.md
"""

import os
from pathlib import Path
from typing import Optional, Dict, List
import re


class PromptLoader:
    """Loads and manages external prompt files for agents."""
    
    def __init__(self, base_dir: Optional[str] = None):
        """
        Initialize the prompt loader.
        
        Args:
            base_dir: Base directory for prompt files. Defaults to agents_evo directory.
        """
        if base_dir is None:
            base_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "agents_evo"
            )
        self.base_dir = Path(base_dir)
        self._prompt_cache: Dict[str, str] = {}
    
    def _parse_prompt_filename(self, filename: str) -> Optional[Dict[str, str]]:
        """
        Parse a prompt filename into its components.
        
        Expected format: {agent_name}.{bias_specialty}.{variant_id}.prompt.md
        
        Returns:
            Dict with keys: agent_name, bias, variant, or None if invalid format
        """
        pattern = r'^([a-z_]+)\.([a-z_]+)\.(v\d+)\.prompt\.md$'
        match = re.match(pattern, filename)
        
        if not match:
            return None
        
        return {
            'agent_name': match.group(1),
            'bias': match.group(2),
            'variant': match.group(3),
            'full_name': filename[:-9]  # Remove '.prompt.md'
        }
    
    def list_available_prompts(self, agent_name: Optional[str] = None) -> List[Dict[str, str]]:
        """
        List all available prompt files, optionally filtered by agent name.
        
        Args:
            agent_name: Optional agent name to filter by
            
        Returns:
            List of dicts with prompt metadata
        """
        prompts = []
        
        for root, dirs, files in os.walk(self.base_dir):
            for filename in files:
                if not filename.endswith('.prompt.md'):
                    continue
                    
                parsed = self._parse_prompt_filename(filename)
                if parsed is None:
                    continue
                
                if agent_name and parsed['agent_name'] != agent_name:
                    continue
                
                # Add relative path
                rel_path = os.path.relpath(root, self.base_dir)
                parsed['category'] = rel_path if rel_path != '.' else 'root'
                parsed['filepath'] = os.path.join(root, filename)
                prompts.append(parsed)
        
        return prompts
    
    def get_prompt_variants(self, agent_name: str) -> Dict[str, List[Dict[str, str]]]:
        """
        Get all available prompt variants for a specific agent.
        
        Args:
            agent_name: Name of the agent (e.g., 'market_analyst', 'bull_researcher')
            
        Returns:
            Dict mapping bias types to lists of variant info
        """
        all_prompts = self.list_available_prompts(agent_name)
        
        variants: Dict[str, List[Dict[str, str]]] = {}
        for prompt in all_prompts:
            bias = prompt['bias']
            if bias not in variants:
                variants[bias] = []
            variants[bias].append(prompt)
        
        return variants
    
    def load_prompt(
        self,
        agent_name: str,
        bias: str = 'default',
        variant: str = 'v1',
        use_cache: bool = True
    ) -> str:
        """
        Load a specific prompt file.
        
        Args:
            agent_name: Name of the agent
            bias: Bias/specialty type (default, aggressive, conservative, etc.)
            variant: Variant version (v1, v2, v3, etc.)
            use_cache: Whether to use cached version if available
            
        Returns:
            The prompt content as a string
            
        Raises:
            FileNotFoundError: If the prompt file doesn't exist
        """
        cache_key = f"{agent_name}.{bias}.{variant}"
        
        if use_cache and cache_key in self._prompt_cache:
            return self._prompt_cache[cache_key]
        
        # Search for the prompt file
        prompt_file = f"{agent_name}.{bias}.{variant}.prompt.md"
        
        # Try in root first, then in subdirectories
        search_paths = [self.base_dir]
        for subdir in ['analysts', 'researchers', 'trader', 'risk_mgmt', 'portfolio']:
            search_paths.append(self.base_dir / subdir)
        
        for search_path in search_paths:
            filepath = search_path / prompt_file
            if filepath.exists():
                content = filepath.read_text(encoding='utf-8')
                self._prompt_cache[cache_key] = content
                return content
        
        # If not found, raise error with helpful message
        available = self.list_available_prompts(agent_name)
        if available:
            available_str = "\n  ".join([p['filepath'] for p in available])
            raise FileNotFoundError(
                f"Prompt not found: {prompt_file}\n"
                f"Available variants for {agent_name}:\n  {available_str}"
            )
        else:
            raise FileNotFoundError(
                f"Prompt not found: {prompt_file}\n"
                f"No prompts found for agent: {agent_name}"
            )
    
    def load_prompt_by_path(self, filepath: str) -> str:
        """
        Load a prompt file by its full path.
        
        Args:
            filepath: Full path to the prompt file
            
        Returns:
            The prompt content as a string
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {filepath}")
        
        content = path.read_text(encoding='utf-8')
        
        # Cache by absolute path
        self._prompt_cache[str(path.absolute())] = content
        return content
    
    def get_default_prompt(self, agent_name: str) -> str:
        """
        Load the default prompt for an agent (bias='default', variant='v1').
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            The default prompt content
        """
        return self.load_prompt(agent_name, bias='default', variant='v1')
    
    def clear_cache(self):
        """Clear the prompt cache."""
        self._prompt_cache.clear()
    
    def reload_all_prompts(self):
        """Reload all prompts from disk, clearing the cache."""
        self.clear_cache()
        # Pre-load all prompts into cache
        for prompt in self.list_available_prompts():
            try:
                self.load_prompt(
                    prompt['agent_name'],
                    prompt['bias'],
                    prompt['variant'],
                    use_cache=False
                )
            except Exception:
                pass  # Skip prompts that can't be loaded


# Global instance for convenience
_default_loader: Optional[PromptLoader] = None


def get_prompt_loader() -> PromptLoader:
    """Get or create the default prompt loader instance."""
    global _default_loader
    if _default_loader is None:
        _default_loader = PromptLoader()
    return _default_loader


def load_agent_prompt(
    agent_name: str,
    bias: str = 'default',
    variant: str = 'v1'
) -> str:
    """
    Convenience function to load a prompt using the default loader.
    
    Args:
        agent_name: Name of the agent
        bias: Bias/specialty type
        variant: Variant version
        
    Returns:
        The prompt content
    """
    return get_prompt_loader().load_prompt(agent_name, bias, variant)
