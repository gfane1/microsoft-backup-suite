# Contributing to OneDrive Backup Tool

Thank you for your interest in contributing to the OneDrive Backup Tool! We welcome contributions from the community.

## How to Contribute

### Reporting Bugs

If you find a bug, please open an issue on GitHub with:
- A clear, descriptive title
- Steps to reproduce the issue
- Expected behavior vs actual behavior
- Your environment (OS, Python version, OneDrive account type)
- Any error messages or logs

### Suggesting Features

We love new ideas! To suggest a feature:
- Open an issue with the label "enhancement"
- Describe the feature and why it would be useful
- Provide examples of how it would work
- Discuss any potential implementation challenges

### Pull Requests

We actively welcome pull requests!

#### Before You Start

1. Check existing issues and PRs to avoid duplicates
2. For major changes, open an issue first to discuss your approach
3. Make sure you can test your changes with a real OneDrive account

#### Pull Request Process

1. **Fork the repository** and create your branch from `main`
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Write clear, commented code
   - Follow the existing code style
   - Keep changes focused (one feature/fix per PR)

3. **Test thoroughly**
   - Test with both personal Microsoft accounts
   - Test resume capability (stop and restart)
   - Test with large file sets if applicable
   - Verify folder structure is preserved

4. **Update documentation**
   - Update README.md if you're adding features
   - Add comments to complex code sections
   - Update docstrings for functions you modify

5. **Commit your changes**
   ```bash
   git commit -m "Add feature: brief description"
   ```
   - Use clear, descriptive commit messages
   - Reference any related issues (e.g., "Fixes #123")

6. **Push to your fork** and submit a pull request
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Wait for review**
   - Respond to feedback
   - Make requested changes
   - Be patient - reviews may take a few days

## Code Style Guidelines

### Python Style
- Follow PEP 8 guidelines
- Use descriptive variable names
- Add docstrings to all functions
- Keep functions focused and single-purpose
- Use type hints where helpful

### Code Organization
- Keep related functionality together
- Extract complex logic into separate functions
- Add comments for non-obvious code
- Handle errors gracefully with try-except blocks

### Example

```python
def download_file(url: str, destination: Path) -> bool:
    """
    Download a file from OneDrive to local storage.

    Args:
        url: Direct download URL from Microsoft Graph API
        destination: Local path where file should be saved

    Returns:
        True if download succeeded, False otherwise
    """
    try:
        response = requests.get(url, timeout=300)
        if response.status_code == 200:
            with open(destination, 'wb') as f:
                f.write(response.content)
            return True
    except Exception as e:
        print(f"Download failed: {e}")
    return False
```

## Areas We'd Love Help With

### High Priority
- [ ] GUI version for non-technical users
- [ ] Support for work/school OneDrive accounts
- [ ] Incremental backup (only download changed files)
- [ ] Compression options for backups
- [ ] Better progress indicators (file size, ETA)
- [ ] Configuration file support
- [ ] Scheduled/automated backups

### Medium Priority
- [ ] Support for shared folders
- [ ] Backup verification/integrity checks
- [ ] Multi-threaded downloads
- [ ] Email notifications on completion

### Nice to Have
- [ ] Docker container version
- [ ] Cloud-to-cloud backup (OneDrive to Google Drive, etc.)
- [ ] Encryption options
- [ ] Backup history and versioning
- [ ] Web interface

## Testing

Before submitting a PR, please test:

1. **Basic functionality**
   - Authentication works
   - Files download correctly
   - Folder structure is preserved

2. **Edge cases**
   - Very large files (>1GB)
   - Special characters in filenames
   - Empty folders
   - Network interruptions

3. **Resume capability**
   - Stop script mid-download (Ctrl+C)
   - Restart and verify it continues from same point
   - Check no duplicate files are created

4. **Error handling**
   - Invalid credentials
   - Disconnected external drive
   - Network failure during download
   - Token expiration

## Security Considerations

When contributing, please:
- Never commit credentials or secrets
- Don't log sensitive user information
- Use secure methods for token storage
- Follow OAuth 2.0 best practices
- Validate all user inputs

## Questions?

Feel free to:
- Open an issue for questions
- Start a discussion on GitHub
- Reach out to maintainers

## Code of Conduct

### Our Standards

- Be respectful
- Welcome newcomers and help them learn
- Focus on what's best for the community
- Show empathy and kindness towards all, not just those you like
- Accept constructive criticism gracefully

### Unacceptable Behavior

- Harassment, trolling, or discriminatory comments
- Publishing others' private information
- Spam or self-promotion unrelated to the project
- Any conduct that could be considered inappropriate in a professional setting

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Recognition

Contributors will be recognized in the project! Significant contributions may be highlighted in:
- README.md credits section
- Release notes
- Project documentation

Thank you for contributing! 🎉
