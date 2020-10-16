'''

Author:: Gurkirt Singh

'''

import os
import json
import time
import pdb
import pickle
import numpy as np
import scipy.io as io  # to save detection as mat files
from data.datasets import is_part_of_subsets, get_filtered_tubes, get_filtered_frames, filter_labels
from modules.tube_helper import get_tube_3Diou, make_det_tube
from modules import utils
logger = utils.get_logger(__name__)

def voc_ap(rec, prec, use_07_metric=False):
    """ ap = voc_ap(rec, prec, [use_07_metric])
    Compute VOC AP given precision and recall.
    If use_07_metric is true, uses the
    VOC 07 11 point method (default:False).
    """
    if use_07_metric:
        # 11 point metric
        ap = 0.
        for t in np.arange(0., 1.1, 0.1):
            if np.sum(rec >= t) == 0:
                p = 0
            else:
                p = np.max(prec[rec >= t])
            ap = ap + p / 11.
    else:
        # correct AP calculation
        # first append sentinel values at the end
        mrec = np.concatenate(([0.], rec, [1.]))
        mpre = np.concatenate(([0.], prec, [0.]))

        # compute the precision envelope
        for i in range(mpre.size - 1, 0, -1):
            mpre[i - 1] = np.maximum(mpre[i - 1], mpre[i])

        # to calculate area under PR curve, look for points
        # where X axis (recall) changes value
        i = np.where(mrec[1:] != mrec[:-1])[0]

        # and sum (\Delta recall) * prec
        ap = np.sum((mrec[i + 1] - mrec[i]) * mpre[i + 1])
    return ap*100


def pr_to_ap(pr):
    """
    Compute AP given precision-recall
    pr is a Nx2 array with first row being precision and second row being recall
    """

    prdif = pr[1:, 1] - pr[:-1, 1]
    prsum = pr[1:, 0] + pr[:-1, 0]

    return np.sum(prdif * prsum * 0.5)


def get_gt_of_cls(gt_boxes, cls):
    cls_gt_boxes = []
    for i in range(gt_boxes.shape[0]):
        if len(gt_boxes.shape) > 1 and int(gt_boxes[i, -1]) == cls:
            cls_gt_boxes.append(gt_boxes[i, :-1])
    return np.asarray(cls_gt_boxes)

def compute_iou_dict(det, cls_gt_boxes):
    # print(cls_gt_boxes, type(cls_gt_boxes))
    cls_gt_boxes = cls_gt_boxes.reshape(-1,4)
    # print(cls_gt_boxes, type(cls_gt_boxes))
    return compute_iou(det['box'], cls_gt_boxes)[0]

def compute_iou(box, cls_gt_boxes):

    ious = np.zeros(cls_gt_boxes.shape[0])

    for m in range(cls_gt_boxes.shape[0]):
        gtbox = cls_gt_boxes[m]

        xmin = max(gtbox[0], box[0])
        ymin = max(gtbox[1], box[1])
        xmax = min(gtbox[2], box[2])
        ymax = min(gtbox[3], box[3])
        iw = np.maximum(xmax - xmin, 0.)
        ih = np.maximum(ymax - ymin, 0.)
        if iw > 0 and ih > 0:
            intsc = iw*ih
        else:
            intsc = 0.0
        union = (gtbox[2] - gtbox[0]) * (gtbox[3] - gtbox[1]) + \
            (box[2] - box[0]) * (box[3] - box[1]) - intsc
        ious[m] = intsc/union

    return ious


def evaluate_detections(gt_boxes, det_boxes, classes=[], iou_thresh=0.5):

    ap_strs = []
    num_frames = len(gt_boxes)
    logger.info('Evaluating for '+ str(num_frames) + ' frames')
    ap_all = np.zeros(len(classes), dtype=np.float32)
    # loop over each class 'cls'
    for cls_ind, class_name in enumerate(classes):
        scores = np.zeros(num_frames * 2000)
        istp = np.zeros(num_frames * 2000)
        det_count = 0
        num_postives = 0.0
        for nf in range(num_frames):  # loop over each frame 'nf'
                # if len(gt_boxes[nf])>0 and len(det_boxes[cls_ind][nf]):
            # get frame detections for class cls in nf
            frame_det_boxes = np.copy(det_boxes[cls_ind][nf])
            # get gt boxes for class cls in nf frame
            cls_gt_boxes = get_gt_of_cls(np.copy(gt_boxes[nf]), cls_ind)
            num_postives += cls_gt_boxes.shape[0]
            # check if there are dection for class cls in nf frame
            if frame_det_boxes.shape[0] > 0:
                # sort in descending order
                sorted_ids = np.argsort(-frame_det_boxes[:, -1])
                for k in sorted_ids:  # start from best scoring detection of cls to end
                    box = frame_det_boxes[k, :-1]  # detection bounfing box
                    score = frame_det_boxes[k, -1]  # detection score
                    ispositive = False  # set ispostive to false every time
                    # we can only find a postive detection
                    if cls_gt_boxes.shape[0] > 0:
                        # if there is atleast one gt bounding for class cls is there in frame nf
                        # compute IOU between remaining gt boxes
                        iou = compute_iou(box, cls_gt_boxes)
                        # and detection boxes
                        # get the max IOU window gt index
                        maxid = np.argmax(iou)
                        # check is max IOU is greater than detection threshold
                        if iou[maxid] >= iou_thresh:
                            ispositive = True  # if yes then this is ture positive detection
                            # remove assigned gt box
                            cls_gt_boxes = np.delete(cls_gt_boxes, maxid, 0)
                    # fill score array with score of current detection
                    scores[det_count] = score
                    if ispositive:
                        # set current detection index (det_count)
                        istp[det_count] = 1
                        #  to 1 if it is true postive example
                    det_count += 1
        if num_postives < 1:
            num_postives = 1
        scores = scores[:det_count]
        istp = istp[:det_count]
        argsort_scores = np.argsort(-scores)  # sort in descending order
        istp = istp[argsort_scores]  # reorder istp's on score sorting
        fp = np.cumsum(istp == 0)  # get false positives
        tp = np.cumsum(istp == 1)  # get  true positives
        fp = fp.astype(np.float64)
        tp = tp.astype(np.float64)
        recall = tp / float(num_postives)  # compute recall
        # compute precision
        precision = tp / np.maximum(tp + fp, np.finfo(np.float64).eps)
        # compute average precision using voc2007 metric
        cls_ap = voc_ap(recall, precision)
        ap_all[cls_ind] = cls_ap
        ap_str = class_name + ' : ' + \
            str(num_postives) + ' : ' + str(det_count) + ' : ' + str(cls_ap)
        ap_strs.append(ap_str)

    mAP = np.mean(ap_all)
    logger.info('mean ap '+ str(mAP))
    return mAP, ap_all, ap_strs


# def filter_labels(labels, n):
#     new_labels = []
#     for k in range(labels.shape[1]):
#         if labels[n, k] > -1:
#             new_labels.append(int(labels[n, k]))
#     return new_labels


def evaluate(gts, dets, all_classes, iou_thresh=0.5):
    # np.mean(ap_all), ap_all, ap_strs
    aps, aps_all, ap_strs = [], [], []
    for nlt in range(len(gts)):
        a, b, c = evaluate_detections(
            gts[nlt], dets[nlt], all_classes[nlt], iou_thresh)
        aps.append(a)
        aps_all.append(b)
        ap_strs.append(c)
    return aps, aps_all, ap_strs


def get_class_ap_from_scores(scores, istp, num_postives):
    # num_postives = np.sum(istp)
    if num_postives < 1:
        num_postives = 1
    argsort_scores = np.argsort(-scores)  # sort in descending order
    istp = istp[argsort_scores]  # reorder istp's on score sorting
    fp = np.cumsum(istp == 0)  # get false positives
    tp = np.cumsum(istp == 1)  # get  true positives
    fp = fp.astype(np.float64)
    tp = tp.astype(np.float64)
    recall = tp / float(num_postives)  # compute recall
    # compute precision
    precision = tp / np.maximum(tp + fp, np.finfo(np.float64).eps)
    # compute average precision using voc2007 metric
    cls_ap = voc_ap(recall, precision)
    return cls_ap


def evaluate_ego(gts, dets, classes):
    ap_strs = []
    num_frames = gts.shape[0]
    logger.info('Evaluating for ' + str(num_frames) + ' frames')
    ap_all = np.zeros(len(classes), dtype=np.float32)

    for cls_ind, class_name in enumerate(classes):
        scores = dets[:, cls_ind]
        istp = np.zeros_like(gts)
        istp[gts == cls_ind] = 1
        det_count = num_frames
        num_postives = np.sum(istp)
        cls_ap = get_class_ap_from_scores(scores, istp, num_postives)
        ap_all[cls_ind] = cls_ap
        ap_str = class_name + ' : ' + \
            str(num_postives) + ' : ' + str(det_count) + ' : ' + str(cls_ap)
        ap_strs.append(ap_str)

    return [np.mean(ap_all)], [ap_all], [ap_strs]


def get_gt_tubes(final_annots, subset, label_type):
    """Get video list form ground truth videos used in subset 
    and their ground truth tubes """

    video_list = []
    tubes = {}
    for videoname in final_annots['db']:
        if is_part_of_subsets(final_annots['db'][videoname]['split_ids'], [subset]):
            video_list.append(videoname)
            tubes[videoname] = get_filtered_tubes(
                label_type+'_tubes', final_annots, videoname)

    return video_list, tubes


def get_det_class_tubes(tubes, cl_id):
    class_tubes = []
    for video, video_tubes in tubes.items():
        for tube in video_tubes:
            if tube['label_id'] == cl_id:
                scores, boxes = tube['scores'], tube['boxes']
                frames, label_id  = tube['frames'], tube['label_id']
                class_tubes.append([video, make_det_tube(scores, boxes, frames, label_id)])
    return class_tubes


def get_gt_class_tubes(tubes, cl_id):
    class_tubes = {}
    for video, video_tubes in tubes.items():
        class_tubes[video] = []
        for tube in video_tubes:
            if tube['label_id'] == cl_id:
                class_tubes[video].append(tube)
    return class_tubes

def compute_class_ap(class_dets, class_gts, match_func, iou_thresh):

    pr = np.empty((len(class_dets) + 1, 2), dtype=np.float32)
    pr[0, 0] = 1.0
    pr[0, 1] = 0.0

    fn = max(1, sum([len(class_gts[iid])
                        for iid in class_gts]))  # false negatives
    num_postives = fn
    fp = 0  # false positives
    tp = 0  # true positives
    
    scores = np.zeros(len(class_dets))
    istp = np.zeros(len(class_dets))

    inv_det_scores = np.asarray([-det[1]['score'] for det in class_dets])
    indexs = np.argsort(inv_det_scores)
    count = 0
    for count, det_id in enumerate(indexs):
        is_positive = False
        detection = class_dets[det_id]
        iid, det = detection
        score = det['score']
        # pdb.set_trace()
        if len(class_gts[iid]) > 0:
            ious = np.asarray([match_func(det, gt)
                                for gt in class_gts[iid]])
            # print(ious)
            max_iou_id = np.argmax(ious)
            if ious[max_iou_id] >= iou_thresh:
                is_positive = True
                del class_gts[iid][max_iou_id]
        
        scores[count] = score
    
        if is_positive:
            istp[count] = 1
            tp += 1
            fn -= 1
        else:
            fp += 1

        pr[count+1, 0] = float(tp) / float(tp + fp)
        pr[count+1, 1] = float(tp) / float(tp + fn)
    
    class_ap = float(100*pr_to_ap(pr))

    return class_ap, num_postives, count


def evaluate_tubes(anno_file, det_file, classes, label_type, subset='val_3', iou_thresh=0.2):

    with open(anno_file, 'r') as fff:
        final_annots = json.load(fff)

    with open(det_file, 'r') as fff:
        detections = json.load(fff)

    ap_all = []
    ap_strs = []
    sap = 0.0
    video_list, gt_tubes = get_gt_tubes(final_annots, subset, label_type)
    det_tubes = {}
    
    for videoname in video_list:
        det_tubes[videoname] = detections[label_type][videoname]

    for cl_id, class_name in enumerate(classes):

        class_dets = get_det_class_tubes(det_tubes, cl_id)
        class_gts = get_gt_class_tubes(gt_tubes, cl_id)

        class_ap, num_postives, count = compute_class_ap(class_dets, class_gts, get_tube_3Diou, iou_thresh)

        sap += class_ap
        ap_all.append(class_ap)
        ap_str = class_name + ' : ' + str(num_postives) + \
            ' : ' + str(count) + ' : ' + str(class_ap)
        ap_strs.append(ap_str)
    mAP = sap/len(classes)
    ap_strs.append('\nMean AP:: {:0.2f}'.format(mAP))
    return mAP, ap_all, ap_strs


def get_gt_frames(final_annots, subsets, label_type):
    """Get video list form ground truth videos used in subset 
    and their ground truth frames """

    video_list = []
    frames = {}
    if not isinstance(subsets, list):
        subsets = [subsets]
    for videoname in final_annots['db']:
        if is_part_of_subsets(final_annots['db'][videoname]['split_ids'], subsets):
            video_list.append(videoname)
            frames = get_filtered_frames(
                label_type, final_annots, videoname, frames)

    return video_list, frames


def get_det_class_frames(dets, cl_id, frame_ids):
    class_dets = []
    for frame_id in dets:
        if frame_id in frame_ids:
            all_frames_dets = dets[frame_id][cl_id]
            for i in range(all_frames_dets.shape[0]):
                det = {'box':all_frames_dets[i,:4], 'score':all_frames_dets[i,4]}
                class_dets.append([frame_id, det])
    return class_dets


def get_gt_class_frames(gts, cl_id):
    frames = {}
    for frame_id, frame in gts.items():
        boxes = []
        for anno in frame:
            if cl_id in anno[1]:
                boxes.append(anno[0].copy())
        frames[frame_id] = boxes

    return frames


def eval_framewise_ego_actions_aarav(final_annots, detections, subsets):
    """Get video list form ground truth videos used in subset 
    and their ground truth frames """


    if not isinstance(subsets, list):
        subsets = [subsets]
    label_key = 'av_actions'
    filtered_gts = []
    filtered_preds = []
    all_labels = final_annots['all_'+label_key+'_labels']
    labels = final_annots[label_key+'_labels']
    for videoname in final_annots['db']:
        if (final_annots['db'][videoname]['split_ids'], subsets):
            label_key = 'av_actions'
            frames = final_annots['db'][videoname]['frames']
            
            for frame_id , frame in frames.items():
                frame_name = '{:08d}'.format(int(frame_id))
                if frame['annotated']>0:
                    gts = filter_labels(frame[label_key+'_ids'], all_labels, labels)
                    filtered_gts.append(gts)
                    frame_name = '{:08d}'.format(int(frame_id))
                    filtered_preds.append(detections[videoname+frame_name])

    gts = np.asarray(filtered_gts)
    preds = np.asarray(filtered_preds)
    return evaluate_ego(gts, preds, labels)
    

def eval_framewise_ego_actions(final_annots, detections, subsets, dataset='arrav'):
    if dataset == 'aarav':
        return eval_framewise_ego_actions_aarav(final_annots, detections, subsets)
    else:
        raise Exception('Not implemented yet eval_framewise_ego_actions')


def evaluate_frames(anno_file, det_file, subset, iou_thresh=0.5, dataset='aarav'):
    with open(anno_file, 'r') as fff:
        final_annots = json.load(fff)

    with open(det_file, 'rb') as fff:
        detections = pickle.load(fff)

    results = {}
    if dataset == 'aarav':
        label_types = ['av_actions'] + ['agent_ness'] + final_annots['label_types']
    else:
        label_types = ['frame_actions', 'action_ness', 'action']
    
    for nlt, label_type in enumerate(label_types):
        if label_type in ['av_actions', 'frame_actions']:
            eval_framewise_ego_actions(final_annots, detections[label_type], subset, dataset)
        else:
            ap_all = []
            ap_strs = []
            sap = 0.0
            _, gt_frames = get_gt_frames(final_annots, subset, label_type)
            
            if nlt==0:
                classes = ['agent_ness']
            else:
                classes = final_annots[label_type+'_labels']
            
            for cl_id, class_name in enumerate(classes):
                ## gather gt of class "class_name" from frames which are not marked igonre
                class_gts = get_gt_class_frames(gt_frames, cl_id)
                frame_ids = [f for f in class_gts.keys()]
                ## gather detection from only that are there in gt or not marked ignore
                class_dets = get_det_class_frames(detections[label_type], cl_id, frame_ids) 
                
                class_ap, num_postives, count = compute_class_ap(class_dets, class_gts, compute_iou_dict, iou_thresh)

                sap += class_ap
                ap_all.append(class_ap)
                ap_str = class_name + ' : ' + str(num_postives) + \
                    ' : ' + str(count) + ' : ' + str(class_ap)
                logger.info(ap_str)
                ap_strs.append(ap_str)
        mAP = sap/len(classes)
        ap_strs.append('\n'+label_type+' Mean AP:: {:0.2f}'.format(mAP))
        results[label_type] = {'mAP':mAP, 'ap_all':ap_all, 'ap_strs':ap_strs}
    
    return results