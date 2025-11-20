from typing import Optional, List
from dataclasses import dataclass, field
from typing import List


@dataclass
class UserInfo:
    id: str
    firstname: str
    surname: str
    email: str
    role: str


@dataclass
class UserAccount:
    username: str
    password: str
    email: str
    info: UserInfo


@dataclass
class Image:
    id: int
    staff: str
    title: str
    description: Optional[str]
    categories: List[str]
    resolution: Optional[str]
    format: Optional[str]
    file_name: Optional[str]
    uploaded_at: Optional[str]
    price: Optional[float]
    event_id: Optional[int]
    url: Optional[str]

    views: int = 0
    downloads: int = 0
    tags: List[str] = field(default_factory=list)
    featured_in: List[str] = field(default_factory=list)
    location: Optional[str] = None
    camera: Optional[str] = None
    license: Optional[str] = None
    published: Optional[str] = None
