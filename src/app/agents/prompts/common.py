MARKDOWN_GUIDELINES = """
### String Field Formatting
ALL string fields in your JSON response must use Markdown formatting:

#### Inline Elements
- Use backticks for `code`, `file_paths`, `function_names`, and `class_names`
- Use **bold** for emphasis on important terms
- Use *italic* for technical terms or variables
- Use [links](relative/path/to/file.ext) for file references
- Use [external links](https://example.com) for documentation

#### Lists & Todos
- Use bullet points (-) for general lists
- Use todo lists for task tracking:
  - [ ] Incomplete task
  - [x] Completed task
  - [ ] → [x] Status change
  - [ ] **Priority**: [link/to/file.py] 

#### Code & Structure
- Use code blocks (```) for multi-line code examples
- Use tables for structured data when appropriate
- Use horizontal rules (---) to separate sections
"""
