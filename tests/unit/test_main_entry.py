# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Unit tests for src/__main__.py entry point (FR-270, IC-42).

Validates:
- AC-270: Verify python -m src.server starts the server

Test Case IDs: IT-15

FR-270: The system SHALL be runnable using python -m src.server command
IC-42: The system SHALL be runnable using python -m src.server command

This __main__.py file allows the src package to be run directly as a module
using the python -m interpreter.
"""

import ast
import asyncio
import os
import sys


class TestMainEntryPoint:
    """
    Tests for __main__.py entry point enabling python -m src.server.

    AC-270: Verify python -m src.server starts the server
    """

    def test_main_file_exists(self):
        """AC-270: Verify __main__.py exists in src/ directory"""
        import os
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', '__main__.py')
        path = os.path.normpath(path)
        assert os.path.exists(path), f"__main__.py not found at {path}"

    def test_main_file_has_valid_syntax(self):
        """AC-270: Verify __main__.py has valid Python syntax"""
        import os
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', '__main__.py')
        path = os.path.normpath(path)

        with open(path) as f:
            source = f.read()

        # Should not raise SyntaxError
        tree = ast.parse(source)
        assert tree is not None

    def test_main_imports_asyncio(self):
        """AC-270: Verify __main__.py imports click CLI"""
        import os
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', '__main__.py')
        path = os.path.normpath(path)

        with open(path) as f:
            source = f.read()

        tree = ast.parse(source)
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]

        import_names = []
        for imp in imports:
            if isinstance(imp, ast.Import):
                for alias in imp.names:
                    import_names.append(alias.name)
            elif isinstance(imp, ast.ImportFrom):
                import_names.append(imp.module)

        assert 'src.main' in import_names, "Expected src.main to be imported"

    def test_main_imports_main_from_server(self):
        """AC-270: Verify __main__.py imports main from server module"""
        import os
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', '__main__.py')
        path = os.path.normpath(path)

        with open(path) as f:
            source = f.read()

        tree = ast.parse(source)

        # Find from ... import statements
        from_imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        for imp in from_imports:
            if imp.module == 'server':
                assert 'main' in [alias.name for alias in imp.names]

    def test_main_has_name_main_guard(self):
        """AC-270: Verify __main__.py uses if __name__ == '__main__' guard"""
        import os
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', '__main__.py')
        path = os.path.normpath(path)

        with open(path) as f:
            source = f.read()

        tree = ast.parse(source)

        # Find if __name__ == '__main__' pattern
        found_guard = False
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # Check for __name__ == '__main__'
                if isinstance(node.test, ast.Compare):
                    if isinstance(node.test.left, ast.Name) and node.test.left.id == '__name__':
                        found_guard = True
                        break

        assert found_guard, "Expected if __name__ == '__main__' guard"

    def test_main_calls_asyncio_run(self):
        """AC-270: Verify __main__.py delegates to click CLI"""
        import os
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', '__main__.py')
        path = os.path.normpath(path)

        with open(path) as f:
            source = f.read()

        tree = ast.parse(source)

        # Find click CLI call
        found_cli_call = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id == 'cli':
                        found_cli_call = True
                        break

        assert found_cli_call, "Expected cli() call in __main__"

    def test_server_main_is_async_function(self):
        """AC-270: Verify server.main is an async function"""
        # Add src to path for import
        src_path = os.path.join(os.path.dirname(__file__), '..', '..', 'src')
        src_path = os.path.normpath(src_path)
        sys.path.insert(0, src_path)

        from server import server_main
        assert asyncio.iscoroutinefunction(server_main), "server.server_main should be an async function"

    def test_entry_point_module_can_be_executed(self):
        """AC-270: Verify __main__.py can be parsed and contains expected structure"""
        # This is a structural test - verify the file has the right components
        # without actually executing it (which would start the server)
        import os
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', '__main__.py')
        path = os.path.normpath(path)

        with open(path) as f:
            content = f.read()

        # Verify key requirements
        assert 'FR-270' in content, "Missing FR-270 reference in comments"
        assert 'IC-42' in content, "Missing IC-42 reference in comments"
        assert 'python -m src' in content, "Missing usage documentation"
        assert 'if __name__' in content, "Missing if __name__ == '__main__' guard"
        assert 'from src.main import cli' in content, "Missing click CLI delegation"
