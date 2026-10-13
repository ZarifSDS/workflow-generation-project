from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase

from apps.home.models import HomePage


class HomeSetUpTests(WagtailPageTestCase):
    """
    Tests for basic page structure setup and HomePage creation.
    """

    def test_root_create(self):
        root_page = Page.objects.get(pk=1)
        self.assertIsNotNone(root_page)

    def test_homepage_create(self):
        root_page = Page.objects.get(pk=1)
        homepage = HomePage(title="Home")
        root_page.add_child(instance=homepage)
        self.assertTrue(HomePage.objects.filter(title="Home").exists())


class HomeTests(WagtailPageTestCase):
    """
    Tests for homepage functionality and rendering.
    """

    def setUp(self):
        """
        Create a homepage instance for testing.
        """
        root_page = Page.get_first_root_node()
        Site.objects.create(hostname="testsite", root_page=root_page, is_default_site=True)
        self.homepage = HomePage(title="Home")
        root_page.add_child(instance=self.homepage)

    def test_homepage_is_renderable(self):
        self.assertPageIsRenderable(self.homepage)

    def test_homepage_template_used(self):
        response = self.client.get(self.homepage.url)
        self.assertTemplateUsed(response, "home/home_page.html")


class HomeContentTests(WagtailPageTestCase):
    """The front page explains the studio, links to the admin and lists only live articles."""

    def setUp(self):
        from apps.content.models import ArticleIndexPage, ArticlePage

        root_page = Page.get_first_root_node()
        Site.objects.create(hostname="testsite", root_page=root_page, is_default_site=True)
        self.homepage = HomePage(title="Home")
        root_page.add_child(instance=self.homepage)
        index = ArticleIndexPage(title="Articles", slug="articles")
        self.homepage.add_child(instance=index)
        index.add_child(
            instance=ArticlePage(title="Live article", slug="live", search_description="Meta", body=[])
        )
        index.add_child(instance=ArticlePage(title="Draft article", slug="draft", live=False, body=[]))

    def test_front_page_links_to_studio_and_lists_live_articles(self):
        response = self.client.get(self.homepage.url)
        html = response.content.decode()
        self.assertIn("Sign in to Content Studio", html)
        self.assertIn('href="/admin/"', html)
        self.assertIn("Live article", html)
        self.assertNotIn("Draft article", html)
        self.assertNotIn("Welcome to your new Wagtail site", html)
