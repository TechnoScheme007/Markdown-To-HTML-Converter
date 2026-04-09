# md2html Demo

A **full CommonMark-compliant** Markdown parser built in a *single Python file*.

## Features at a Glance

| Feature            | Status |  Notes              |
|:-------------------|:------:|--------------------:|
| ATX Headings       |   Yes  | `#` through `######` |
| Setext Headings    |   Yes  | Underline style     |
| Bold / Italic      |   Yes  | `*` and `_` syntax  |
| Strikethrough      |   Yes  | `~~text~~`          |
| Inline Code        |   Yes  | Backtick syntax     |
| Fenced Code Blocks |   Yes  | With highlighting   |
| Links & Images     |   Yes  | Inline + reference  |
| Ordered Lists      |   Yes  | Nested support      |
| Unordered Lists    |   Yes  | Nested support      |
| Blockquotes        |   Yes  | Recursive nesting   |
| Tables             |   Yes  | GFM alignment       |
| Horizontal Rules   |   Yes  | `---`, `***`, `___` |

---

## Code Blocks

### Python

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class User:
    name: str
    email: str
    age: Optional[int] = None

    def greet(self) -> str:
        return f"Hello, I'm {self.name}!"

users = [User("Alice", "alice@example.com", 30),
         User("Bob", "bob@example.com")]

for user in users:
    print(user.greet())
```

### JavaScript

```javascript
async function fetchData(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    console.error('Failed to fetch:', error.message);
    return null;
  }
}

const data = await fetchData('https://api.example.com/data');
console.log(data);
```

### Rust

```rust
use std::collections::HashMap;

fn word_count(text: &str) -> HashMap<&str, usize> {
    let mut counts = HashMap::new();
    for word in text.split_whitespace() {
        *counts.entry(word).or_insert(0) += 1;
    }
    counts
}

fn main() {
    let text = "hello world hello rust world";
    let counts = word_count(text);
    for (word, count) in &counts {
        println!("{word}: {count}");
    }
}
```

## Blockquotes

> "The best way to predict the future is to invent it."
>
> — Alan Kay

> **Nested blockquotes** also work:
>
> > This is a nested blockquote.
> > It can contain *any* Markdown.

## Lists

### Unordered (nested)

- Fruits
  - Apples
    - Granny Smith
    - Fuji
  - Bananas
  - Oranges
- Vegetables
  - Carrots
  - Broccoli

### Ordered (nested)

1. Set up the project
   1. Clone the repository
   2. Install dependencies
   3. Configure environment
2. Write code
   - Follow the style guide
   - Write tests first
3. Deploy
   1. Run CI pipeline
   2. Push to production

## Inline Formatting

This paragraph has **bold text**, *italic text*, ***bold and italic***,
`inline code`, and ~~strikethrough~~.

Here's a [link to GitHub](https://github.com "GitHub Homepage") and an
auto-detected link: <https://example.com>.

## Images

![Placeholder Image](https://via.placeholder.com/600x200/0d1117/58a6ff?text=md2html "md2html banner")

## Setext Heading (H1)
===

### This is H3

#### This is H4

##### This is H5

###### This is H6

---

*Built with md2html — zero external dependencies required.*
