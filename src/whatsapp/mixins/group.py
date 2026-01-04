import logging
from typing import List

from ..protocols import WhatsAppClientProtocol
from ..jid import normalize_jid

from ..models import (
    CreateGroupRequest,
    CreateGroupResponse,
    ManageParticipantRequest,
    ManageParticipantResponse,
    JoinGroupRequest,
    LeaveGroupRequest,
    GenericResponse,
    GroupResponse,
    Participant,
)

logger = logging.getLogger(__name__)


class GroupMixin(WhatsAppClientProtocol):
    async def create_group(self, request: CreateGroupRequest) -> CreateGroupResponse:
        response = await self._post("/group", json=request)
        return CreateGroupResponse.model_validate_json(response.content)

    async def add_participants(
        self, request: ManageParticipantRequest
    ) -> ManageParticipantResponse:
        response = await self._post("/group/participants", json=request)
        return ManageParticipantResponse.model_validate_json(response.content)

    async def remove_participants(
        self, request: ManageParticipantRequest
    ) -> ManageParticipantResponse:
        response = await self._post("/group/participants/remove", json=request)
        return ManageParticipantResponse.model_validate_json(response.content)

    async def promote_participants(
        self, request: ManageParticipantRequest
    ) -> ManageParticipantResponse:
        response = await self._post("/group/participants/promote", json=request)
        return ManageParticipantResponse.model_validate_json(response.content)

    async def demote_participants(
        self, request: ManageParticipantRequest
    ) -> ManageParticipantResponse:
        response = await self._post("/group/participants/demote", json=request)
        return ManageParticipantResponse.model_validate_json(response.content)

    async def join_group_with_link(self, link: str) -> GenericResponse:
        response = await self._post(
            "/group/join-with-link", json=JoinGroupRequest(link=link)
        )
        return GenericResponse.model_validate_json(response.content)

    async def leave_group(self, group_id: str) -> GenericResponse:
        response = await self._post(
            "/group/leave", json=LeaveGroupRequest(group_id=group_id)
        )
        return GenericResponse.model_validate_json(response.content)

    async def get_group_members(self, group_jid: str) -> List[Participant]:
        """
        Get the list of participants in a specific group.

        Args:
            group_jid: The JID of the group

        Returns:
            List of Participant objects representing group members
        """
        # Normalize the group JID
        normalized_jid = normalize_jid(group_jid)
        logger.info(f"Looking for group members, normalized JID: {normalized_jid}")

        # Get all groups and find the matching one
        response = await self._get("/user/my/groups")
        groups_response = GroupResponse.model_validate_json(response.content)

        if not groups_response.results or not groups_response.results.data:
            logger.warning("No groups returned from WhatsApp API")
            return []

        logger.info(f"Found {len(groups_response.results.data)} groups from API")

        for group in groups_response.results.data:
            group_normalized = normalize_jid(group.JID)
            logger.debug(f"Checking group: {group_normalized} (name: {group.Name})")
            if group_normalized == normalized_jid:
                logger.info(f"Found matching group with {len(group.Participants)} participants")
                # Log participant JIDs for debugging
                for p in group.Participants:
                    logger.info(f"Participant: JID={p.JID}, LID={p.LID}, DisplayName={p.DisplayName}")
                return group.Participants

        logger.warning(f"Group {normalized_jid} not found in API response")
        return []
