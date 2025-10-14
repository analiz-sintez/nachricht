import pytest
from unittest.mock import Mock, AsyncMock, patch

from .routing import Router, CommandPeg, CallbackPeg, ReactionPeg, MessagePeg
from .context import Context, Emoji
from ..auth import User


@pytest.fixture
def router():
    """Provides a fresh Router instance for each test."""
    return Router()


class TestRouterPegs:
    """Tests that router decorators correctly create and register pegs."""

    def test_command_peg(self, router):
        """Test the @router.command decorator."""
        description = "Test command"
        conditions = {"state": "initial"}

        @router.command(
            "test",
            args=["arg1"],
            description=description,
            conditions=conditions,
        )
        def dummy_command_handler():
            pass

        assert len(router.command_pegs) == 1
        peg = router.command_pegs[0]
        assert isinstance(peg, CommandPeg)
        assert peg.fn == dummy_command_handler
        assert peg.name == "test"
        assert peg.args == ["arg1"]
        assert peg.description == description
        assert peg.conditions == conditions

    def test_callback_query_peg(self, router):
        """Test the @router.callback_query decorator."""
        pattern = r"^test_callback"

        @router.callback_query(pattern)
        def dummy_callback_handler():
            pass

        assert len(router.callback_pegs) == 1
        peg = router.callback_pegs[0]
        assert isinstance(peg, CallbackPeg)
        assert peg.fn == dummy_callback_handler
        assert peg.pattern == pattern
        assert peg.conditions is None

    def test_reaction_peg(self, router):
        """Test the @router.reaction decorator."""
        emojis = [Emoji.SMILE, Emoji.THUMBSUP]
        conditions = {"user_is_premium": True}

        @router.reaction(emojis, conditions=conditions)
        def dummy_reaction_handler():
            pass

        assert len(router.reaction_pegs) == 1
        peg = router.reaction_pegs[0]
        assert isinstance(peg, ReactionPeg)
        assert peg.fn == dummy_reaction_handler
        assert peg.emojis == emojis
        assert peg.conditions == conditions

    def test_message_peg(self, router):
        """Test the @router.message decorator."""
        pattern = ".*"
        conditions = {"in_conversation": True}

        @router.message(pattern, conditions=conditions)
        def dummy_message_handler():
            pass

        assert len(router.message_pegs) == 1
        peg = router.message_pegs[0]
        assert isinstance(peg, MessagePeg)
        assert peg.fn == dummy_message_handler
        assert peg.pattern == pattern
        assert peg.conditions == conditions


@pytest.mark.asyncio
class TestRouterDecorators:
    """Tests the functionality of the decorators like help and authorize."""

    @pytest.fixture
    def mock_context(self):
        """Provides a mock context object."""
        ctx = AsyncMock(spec=Context)
        ctx.send_message = AsyncMock(return_value="fake_message")
        # Mock the context() method to return a dictionary
        ctx.context.return_value = {}
        return ctx

    async def test_help_decorator(self, router, mock_context):
        """Test that @router.help adds a command and reaction handler."""
        help_text = "This is some help."

        @router.help(help_text)
        async def helpful_handler(ctx: Context):
            return await ctx.send_message("Original Message")

        # 1. Check if it added the /help command peg
        assert len(router.command_pegs) == 1
        help_command_peg = router.command_pegs[0]
        assert help_command_peg.name == "help"
        assert "_help" in help_command_peg.conditions

        # 2. Check if it added the reaction peg
        assert len(router.reaction_pegs) == 1
        help_reaction_peg = router.reaction_pegs[0]
        assert Emoji.THINKING in help_reaction_peg.emojis
        assert "_help" in help_reaction_peg.conditions

        # 3. Test the wrapped function's behavior
        await helpful_handler(ctx=mock_context)

        # It should call the original function's send_message
        mock_context.send_message.assert_called_once_with("Original Message")

        # It should add the _help hash to the message context
        mock_context.context.assert_called_once_with("fake_message")
        assert "_help" in mock_context.context.return_value

    @pytest.mark.asyncio
    async def test_authorize_decorator_success(self, router, mock_context):
        """Test @router.authorize allows access for an authorized user."""

        # Mock the config
        class Config:
            AUTHENTICATION = {
                "allowed_logins": ["testuser"],
                "blocked_logins": [],
                "admin_logins": [],
            }

        router.config = Config

        # Mock get_user to return a user
        mock_user = User(login="testuser")

        # Mock the context to have a user
        mock_context.account.login = "testuser"

        inner_handler = AsyncMock()

        # This needs patching `get_user` from `nachricht.messenger.routing`
        from . import routing

        with patch.object(
            routing, "get_user", return_value=mock_user
        ) as mock_get_user:

            @router.authorize()
            async def protected_handler(ctx: Context, user: User):
                await inner_handler(ctx, user)

            await protected_handler(ctx=mock_context)

            mock_get_user.assert_called_once_with("testuser")
            inner_handler.assert_awaited_once()
            # Check that the user object was passed correctly
            called_user = inner_handler.call_args[0][1]
            assert called_user == mock_user

    @pytest.mark.asyncio
    async def test_authorize_decorator_failure(self, router, mock_context):
        """Test @router.authorize blocks an unauthorized user."""

        # Mock the config
        class Config:
            AUTHENTICATION = {
                "allowed_logins": ["allowed_user"],
                "blocked_logins": [],
                "admin_logins": [],
            }

        router.config = Config

        # Mock get_user to return a user
        mock_user = User(login="testuser")

        mock_context.account.login = "testuser"

        inner_handler = AsyncMock()

        from . import routing

        with patch.object(
            routing, "get_user", return_value=mock_user
        ) as mock_get_user:

            @router.authorize()
            async def protected_handler(ctx: Context, user: User):
                await inner_handler(ctx, user)

            with pytest.raises(Exception, match="Not allowed."):
                await protected_handler(ctx=mock_context)

            mock_get_user.assert_called_once_with("testuser")
            inner_handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authorize_admin_decorator(self, router, mock_context):
        """Test @router.authorize(admin=True) for admin access."""

        class Config:
            AUTHENTICATION = {
                "allowed_logins": ["adminuser"],
                "blocked_logins": [],
                "admin_logins": ["adminuser"],
            }

        router.config = Config

        mock_user = User(login="adminuser")
        mock_context.account.login = "adminuser"
        inner_handler = AsyncMock()

        from . import routing

        with patch.object(routing, "get_user", return_value=mock_user):

            @router.authorize(admin=True)
            async def admin_handler(ctx: Context, user: User):
                await inner_handler(ctx, user)

            await admin_handler(ctx=mock_context)
            inner_handler.assert_awaited_once()

        # Now test with a non-admin user
        router.config.AUTHENTICATION["allowed_logins"].append("nonadmin")
        mock_user_non_admin = User(login="nonadmin")
        mock_context.account.login = "nonadmin"
        inner_handler.reset_mock()

        with patch.object(
            routing, "get_user", return_value=mock_user_non_admin
        ):

            @router.authorize(admin=True)
            async def admin_handler_2(ctx: Context, user: User):
                await inner_handler(ctx, user)

            with pytest.raises(Exception, match="Only admins allowed."):
                await admin_handler_2(ctx=mock_context)
            inner_handler.assert_not_awaited()
