from bs4 import BeautifulSoup, NavigableString, Comment

def mark_interactive_elements(html_content: str) -> str:
    """
    Анализирует HTML, находит все интерактивные элементы и помечает их
    атрибутом 'data-ornold-id'.

    Возвращает "очищенный" и размеченный HTML в виде строки.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Удаляем ненужные теги, которые мешают LLM
    for tag in soup.find_all(['script', 'style', 'svg', 'path']):
        tag.decompose()

    # 2. Очищаем текст от лишних пробелов (очень важно для LLM)
    for element in soup.find_all(string=True):
        if isinstance(element, (NavigableString, Comment)):
            continue
        # Заменяем множественные пробелы и переносы строк на один пробел
        cleaned_text = ' '.join(element.strip().split())
        element.replace_with(cleaned_text)

    # 3. Находим и нумеруем интерактивные элементы
    interactive_tags = ['a', 'button', 'input', 'textarea', 'select', '[role="button"]', '[role="link"]']
    
    element_id_counter = 1
    for selector in interactive_tags:
        for element in soup.select(selector):
            # Пропускаем скрытые элементы, они не нужны для взаимодействия
            if 'style' in element.attrs and 'display: none' in element['style']:
                continue
                
            element['data-ornold-id'] = str(element_id_counter)
            element_id_counter += 1
            
    # Возвращаем тело документа, т.к. head для принятия решений не нужен
    body_content = soup.find('body')
    return str(body_content) if body_content else ""

if __name__ == '__main__':
    # Пример использования для отладки
    test_html = """
    <html>
    <head>
        <title>Test Page</title>
        <style>.hidden { display: none; }</style>
    </head>
    <body>
        <h1>Welcome</h1>
        <p>Some text here.   And more     text.
        </p>
        <a href="/login">Click to Login</a>
        <button type="submit">Submit Form</button>
        <input type="text" placeholder="Username">
        <input type="password" class="hidden">
        <div role="button" tabindex="0">Custom Button</div>
        <script>alert('hello');</script>
    </body>
    </html>
    """
    marked_html = mark_interactive_elements(test_html)
    print(marked_html)
    
    # Ожидаемый результат (примерный):
    # <body data-ornold-id-body="1"><h1>Welcome</h1><p>Some text here. And more text.</p><a data-ornold-id="1" href="/login">Click to Login</a><button data-ornold-id="2" type="submit">Submit Form</button><input data-ornold-id="3" placeholder="Username" type="text"/><div data-ornold-id="4" role="button" tabindex="0">Custom Button</div></body> 