window.DEMO_DATA = {
  "5ep": {
    "info": {
      "codebase_version": "v2.1",
      "robot_type": "so101_follower",
      "total_episodes": 5,
      "total_frames": 5370,
      "total_tasks": 1,
      "total_videos": 10,
      "total_chunks": 1,
      "chunks_size": 1000,
      "fps": 30.0,
      "splits": {
        "train": "0:5"
      },
      "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
      "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
      "features": {
        "action": {
          "dtype": "float32",
          "shape": [
            6
          ],
          "names": [
            "shoulder_pan.pos",
            "shoulder_lift.pos",
            "elbow_flex.pos",
            "wrist_flex.pos",
            "wrist_roll.pos",
            "gripper.pos"
          ]
        },
        "observation.state": {
          "dtype": "float32",
          "shape": [
            6
          ],
          "names": [
            "shoulder_pan.pos",
            "shoulder_lift.pos",
            "elbow_flex.pos",
            "wrist_flex.pos",
            "wrist_roll.pos",
            "gripper.pos"
          ]
        },
        "observation.images.wrist": {
          "dtype": "video",
          "shape": [
            480,
            640,
            3
          ],
          "names": [
            "height",
            "width",
            "channels"
          ],
          "info": {
            "video.fps": 30.0,
            "video.height": 480,
            "video.width": 640,
            "video.channels": 3,
            "video.codec": "h264",
            "video.pix_fmt": "yuv420p",
            "video.is_depth_map": false,
            "has_audio": false
          }
        },
        "observation.images.front": {
          "dtype": "video",
          "shape": [
            480,
            640,
            3
          ],
          "names": [
            "height",
            "width",
            "channels"
          ],
          "info": {
            "video.fps": 30.0,
            "video.height": 480,
            "video.width": 640,
            "video.channels": 3,
            "video.codec": "h264",
            "video.pix_fmt": "yuv420p",
            "video.is_depth_map": false,
            "has_audio": false
          }
        },
        "timestamp": {
          "dtype": "float32",
          "shape": [
            1
          ],
          "names": null
        },
        "frame_index": {
          "dtype": "int64",
          "shape": [
            1
          ],
          "names": null
        },
        "episode_index": {
          "dtype": "int64",
          "shape": [
            1
          ],
          "names": null
        },
        "index": {
          "dtype": "int64",
          "shape": [
            1
          ],
          "names": null
        },
        "task_index": {
          "dtype": "int64",
          "shape": [
            1
          ],
          "names": null
        }
      }
    },
    "episodes": [
      {
        "episode_index": 0,
        "task": "Take the red block and put it in the white box",
        "length": 1039
      },
      {
        "episode_index": 1,
        "task": "Take the red block and put it in the white box",
        "length": 989
      },
      {
        "episode_index": 2,
        "task": "Take the red block and put it in the white box",
        "length": 1143
      },
      {
        "episode_index": 3,
        "task": "Take the red block and put it in the white box",
        "length": 1085
      },
      {
        "episode_index": 4,
        "task": "Take the red block and put it in the white box",
        "length": 1114
      }
    ],
    "tasks": [
      {
        "task_index": 0,
        "task": "Take the red block and put it in the white box"
      }
    ],
    "provenance": [
      {
        "episode_index": 0,
        "task": "Take the red block and put it in the white box",
        "source_dataset": "/home/mekala/project/transfers/dataset/Uni",
        "source_episode_index": 0,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.gripper",
          "front": "observation.images.right_side"
        }
      },
      {
        "episode_index": 1,
        "task": "Take the red block and put it in the white box",
        "source_dataset": "/home/mekala/project/transfers/dataset/Uni",
        "source_episode_index": 1,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.gripper",
          "front": "observation.images.right_side"
        }
      },
      {
        "episode_index": 2,
        "task": "Take the red block and put it in the white box",
        "source_dataset": "/home/mekala/project/transfers/dataset/Uni",
        "source_episode_index": 2,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.gripper",
          "front": "observation.images.right_side"
        }
      },
      {
        "episode_index": 3,
        "task": "Take the red block and put it in the white box",
        "source_dataset": "/home/mekala/project/transfers/dataset/Uni",
        "source_episode_index": 3,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.gripper",
          "front": "observation.images.right_side"
        }
      },
      {
        "episode_index": 4,
        "task": "Take the red block and put it in the white box",
        "source_dataset": "/home/mekala/project/transfers/dataset/Uni",
        "source_episode_index": 4,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.gripper",
          "front": "observation.images.right_side"
        }
      }
    ],
    "stats": {
      "action": {
        "min": [
          -60.0,
          -99.745,
          -30.149,
          13.541,
          -13.928,
          0.729
        ],
        "max": [
          26.08,
          38.174,
          99.73,
          99.829,
          20.657,
          30.713
        ],
        "mean": [
          -9.28,
          -44.282,
          32.349,
          59.737,
          -0.391,
          6.635
        ],
        "std": [
          20.708,
          42.711,
          46.478,
          20.975,
          5.389,
          7.939
        ],
        "count": [
          5370
        ]
      },
      "observation.state": {
        "min": [
          -59.533,
          -98.978,
          -24.933,
          15.427,
          -13.685,
          1.841
        ],
        "max": [
          25.438,
          39.949,
          99.193,
          99.32,
          20.229,
          30.243
        ],
        "mean": [
          -9.21,
          -43.017,
          34.657,
          60.365,
          -0.393,
          9.549
        ],
        "std": [
          20.746,
          43.66,
          45.116,
          20.713,
          5.353,
          8.098
        ],
        "count": [
          5370
        ]
      },
      "timestamp": {
        "min": [
          0.0
        ],
        "max": [
          38.067
        ],
        "mean": [
          17.93
        ],
        "std": [
          10.414
        ],
        "count": [
          5370
        ]
      },
      "frame_index": {
        "min": [
          0
        ],
        "max": [
          1142
        ],
        "mean": [
          537.89
        ],
        "std": [
          312.407
        ],
        "count": [
          5370
        ]
      },
      "episode_index": {
        "min": [
          0
        ],
        "max": [
          4
        ],
        "mean": [
          2.046
        ],
        "std": [
          1.41
        ],
        "count": [
          5370
        ]
      },
      "index": {
        "min": [
          0
        ],
        "max": [
          5369
        ],
        "mean": [
          2684.5
        ],
        "std": [
          1550.185
        ],
        "count": [
          5370
        ]
      },
      "task_index": {
        "min": [
          0
        ],
        "max": [
          0
        ],
        "mean": [
          0.0
        ],
        "std": [
          0.0
        ],
        "count": [
          5370
        ]
      }
    },
    "clips": {
      "1": {
        "front": "media/5ep/front_ep01.mp4",
        "wrist": "media/5ep/wrist_ep01.mp4"
      },
      "3": {
        "front": "media/5ep/front_ep03.mp4"
      }
    }
  },
  "assembled_lerobot_v21": {
    "info": {
      "codebase_version": "v2.1",
      "robot_type": "so101_follower",
      "total_episodes": 10,
      "total_frames": 55254,
      "total_tasks": 1,
      "total_videos": 20,
      "total_chunks": 1,
      "chunks_size": 1000,
      "fps": 30.0,
      "splits": {
        "train": "0:10"
      },
      "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
      "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
      "features": {
        "action": {
          "dtype": "float32",
          "shape": [
            6
          ],
          "names": [
            "shoulder_pan.pos",
            "shoulder_lift.pos",
            "elbow_flex.pos",
            "wrist_flex.pos",
            "wrist_roll.pos",
            "gripper.pos"
          ]
        },
        "observation.state": {
          "dtype": "float32",
          "shape": [
            6
          ],
          "names": [
            "shoulder_pan.pos",
            "shoulder_lift.pos",
            "elbow_flex.pos",
            "wrist_flex.pos",
            "wrist_roll.pos",
            "gripper.pos"
          ]
        },
        "observation.images.wrist": {
          "dtype": "video",
          "shape": [
            480,
            640,
            3
          ],
          "names": [
            "height",
            "width",
            "channels"
          ],
          "info": {
            "video.fps": 30.0,
            "video.height": 480,
            "video.width": 640,
            "video.channels": 3,
            "video.codec": "h264",
            "video.pix_fmt": "yuv420p",
            "video.is_depth_map": false,
            "has_audio": false
          }
        },
        "observation.images.front": {
          "dtype": "video",
          "shape": [
            480,
            640,
            3
          ],
          "names": [
            "height",
            "width",
            "channels"
          ],
          "info": {
            "video.fps": 30.0,
            "video.height": 480,
            "video.width": 640,
            "video.channels": 3,
            "video.codec": "h264",
            "video.pix_fmt": "yuv420p",
            "video.is_depth_map": false,
            "has_audio": false
          }
        },
        "timestamp": {
          "dtype": "float32",
          "shape": [
            1
          ],
          "names": null
        },
        "frame_index": {
          "dtype": "int64",
          "shape": [
            1
          ],
          "names": null
        },
        "episode_index": {
          "dtype": "int64",
          "shape": [
            1
          ],
          "names": null
        },
        "index": {
          "dtype": "int64",
          "shape": [
            1
          ],
          "names": null
        },
        "task_index": {
          "dtype": "int64",
          "shape": [
            1
          ],
          "names": null
        }
      }
    },
    "episodes": [
      {
        "episode_index": 0,
        "task": "Hanoi tower.",
        "length": 6332
      },
      {
        "episode_index": 1,
        "task": "Hanoi tower.",
        "length": 6386
      },
      {
        "episode_index": 2,
        "task": "Hanoi tower.",
        "length": 5000
      },
      {
        "episode_index": 3,
        "task": "Hanoi tower.",
        "length": 5813
      },
      {
        "episode_index": 4,
        "task": "Hanoi tower.",
        "length": 1994
      },
      {
        "episode_index": 5,
        "task": "Hanoi tower.",
        "length": 4768
      },
      {
        "episode_index": 6,
        "task": "Hanoi tower.",
        "length": 5257
      },
      {
        "episode_index": 7,
        "task": "Hanoi tower.",
        "length": 5229
      },
      {
        "episode_index": 8,
        "task": "Hanoi tower.",
        "length": 8879
      },
      {
        "episode_index": 9,
        "task": "Hanoi tower.",
        "length": 5596
      }
    ],
    "tasks": [
      {
        "task_index": 0,
        "task": "Hanoi tower."
      }
    ],
    "provenance": [
      {
        "episode_index": 0,
        "task": "Hanoi tower.",
        "source_dataset": "/home/mekala/project/transfers/dataset/hanoi",
        "source_episode_index": 0,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.wrist",
          "front": "observation.images.base"
        }
      },
      {
        "episode_index": 1,
        "task": "Hanoi tower.",
        "source_dataset": "/home/mekala/project/transfers/dataset/hanoi",
        "source_episode_index": 14,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.wrist",
          "front": "observation.images.base"
        }
      },
      {
        "episode_index": 2,
        "task": "Hanoi tower.",
        "source_dataset": "/home/mekala/project/transfers/dataset/hanoi",
        "source_episode_index": 19,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.wrist",
          "front": "observation.images.base"
        }
      },
      {
        "episode_index": 3,
        "task": "Hanoi tower.",
        "source_dataset": "/home/mekala/project/transfers/dataset/hanoi",
        "source_episode_index": 23,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.wrist",
          "front": "observation.images.base"
        }
      },
      {
        "episode_index": 4,
        "task": "Hanoi tower.",
        "source_dataset": "/home/mekala/project/transfers/dataset/hanoi",
        "source_episode_index": 27,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.wrist",
          "front": "observation.images.base"
        }
      },
      {
        "episode_index": 5,
        "task": "Hanoi tower.",
        "source_dataset": "/home/mekala/project/transfers/dataset/hanoi",
        "source_episode_index": 32,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.wrist",
          "front": "observation.images.base"
        }
      },
      {
        "episode_index": 6,
        "task": "Hanoi tower.",
        "source_dataset": "/home/mekala/project/transfers/dataset/hanoi",
        "source_episode_index": 36,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.wrist",
          "front": "observation.images.base"
        }
      },
      {
        "episode_index": 7,
        "task": "Hanoi tower.",
        "source_dataset": "/home/mekala/project/transfers/dataset/hanoi",
        "source_episode_index": 40,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.wrist",
          "front": "observation.images.base"
        }
      },
      {
        "episode_index": 8,
        "task": "Hanoi tower.",
        "source_dataset": "/home/mekala/project/transfers/dataset/hanoi",
        "source_episode_index": 45,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.wrist",
          "front": "observation.images.base"
        }
      },
      {
        "episode_index": 9,
        "task": "Hanoi tower.",
        "source_dataset": "/home/mekala/project/transfers/dataset/hanoi",
        "source_episode_index": 49,
        "checkpoint_revision": 5,
        "updated_by": "operator",
        "flags": [],
        "camera_mapping": {
          "wrist": "observation.images.wrist",
          "front": "observation.images.base"
        }
      }
    ],
    "stats": {
      "action": {
        "min": [
          -41.045,
          27.773,
          -4.834,
          -24.258,
          -21.621,
          -0.344
        ],
        "max": [
          33.486,
          195.205,
          182.373,
          101.338,
          146.777,
          60.877
        ],
        "mean": [
          1.894,
          106.127,
          101.896,
          56.784,
          65.164,
          9.56
        ],
        "std": [
          14.313,
          52.158,
          51.296,
          19.425,
          40.567,
          12.569
        ],
        "count": [
          55254
        ]
      },
      "observation.state": {
        "min": [
          -41.045,
          26.719,
          -1.494,
          -23.291,
          -20.039,
          0.325
        ],
        "max": [
          33.135,
          192.92,
          181.934,
          101.25,
          145.986,
          60.65
        ],
        "mean": [
          1.763,
          103.796,
          103.187,
          57.143,
          65.061,
          11.511
        ],
        "std": [
          14.317,
          52.66,
          50.471,
          19.312,
          40.771,
          12.001
        ],
        "count": [
          55254
        ]
      },
      "timestamp": {
        "min": [
          0.0
        ],
        "max": [
          295.933
        ],
        "mean": [
          99.978
        ],
        "std": [
          64.666
        ],
        "count": [
          55254
        ]
      },
      "frame_index": {
        "min": [
          0
        ],
        "max": [
          8878
        ],
        "mean": [
          2999.341
        ],
        "std": [
          1939.968
        ],
        "count": [
          55254
        ]
      },
      "episode_index": {
        "min": [
          0
        ],
        "max": [
          9
        ],
        "mean": [
          4.618
        ],
        "std": [
          3.063
        ],
        "count": [
          55254
        ]
      },
      "index": {
        "min": [
          0
        ],
        "max": [
          55253
        ],
        "mean": [
          27626.5
        ],
        "std": [
          15950.456
        ],
        "count": [
          55254
        ]
      },
      "task_index": {
        "min": [
          0
        ],
        "max": [
          0
        ],
        "mean": [
          0.0
        ],
        "std": [
          0.0
        ],
        "count": [
          55254
        ]
      }
    },
    "clips": {
      "4": {
        "front": "media/assembled_lerobot_v21/front_ep04.mp4",
        "wrist": "media/assembled_lerobot_v21/wrist_ep04.mp4"
      }
    }
  }
};