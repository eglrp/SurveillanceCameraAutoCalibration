import numpy as np
import cv2 as cv
import time, datetime
from matplotlib import pyplot as plt
import operator
import math

from mpl_toolkits.mplot3d import Axes3D
from matplotlib import cm
from numpy import linspace
import argparse
from imutils.object_detection import non_max_suppression
from numpy.linalg import inv
from math import log10, floor

IsEachFrameDebug = False
hog_threshold = 0.8

def inside(r, q):
    rx, ry, rw, rh = r
    qx, qy, qw, qh = q
    return rx > qx and ry > qy and rx + rw < qx + qw and ry + rh < qy + qh


def draw_detections(img, rects, thickness = 1):
    for x, y, w, h in rects:
        # the HOG detector returns slightly larger rectangles than the real objects.
        # so we slightly shrink the rectangles to get a nicer output.
        pad_w, pad_h = int(0.15*w), int(0.05*h)
        cv.rectangle(img, (x+pad_w, y+pad_h), (x+w-pad_w, y+h-pad_h), (0, 255, 0), thickness)

def inverse_homogeneoux_matrix(M):
    R = M[0:3, 0:3]
    T = M[0:3, 3]
    M_inv = np.identity(4)
    M_inv[0:3, 0:3] = R.T
    M_inv[0:3, 3] = -(R.T).dot(T)

    return M_inv

def transform_to_matplotlib_frame(cMo, X, inverse=False):
    M = np.identity(4)
    M[1,1] = 0
    M[1,2] = 1
    M[2,1] = -1
    M[2,2] = 0

    if inverse:
        return M.dot(inverse_homogeneoux_matrix(cMo).dot(X))
    else:
        return M.dot(cMo.dot(X))

def round_to_1(x, sig=2):
    if x == 0:
        return 0
    else:
        return round(x, sig-int(floor(log10(abs(x))))-1)

def GetWindowWithAxis(Size_of_w, physical_size):
    int_size = int(Size_of_w*0.5)
    center = (int_size, int_size)
    px_of_meter = int(Size_of_w/physical_size)
    img = np.zeros((Size_of_w, Size_of_w, 3), np.uint8)
    img = cv.line(img, center, (center[0], center[1]+px_of_meter), (0,0,255), 3)
    img = cv.line(img, center, (center[0]-px_of_meter, center[1]), (0,255,0), 3)
    return img

def PrintLocalization(Lmap, bigger_frame, pick, ratio, Size_of_w, physical_size, camera_matrix_manual, dist_coefs_manual, ref_rvec, ref_tvec, calib_corners):
    Lmap_localized = Lmap.copy()
    bigger_frame_reproject = bigger_frame.copy()

    px_of_meter = 1.0*Size_of_w/physical_size
    rot, jaco = cv.Rodrigues(ref_rvec)
    #ext = np.vstack((np.hstack((rot, ref_tvec)), np.array([0, 0, 0, 1])))
    #print(ext)
    #ext_inv = inv(ext)
    human_height=1.7
    for (xA, yA, xB, yB) in pick:
        head_pt = [(xA+xB)*0.5*ratio, min(yA, yB)*ratio] # (u1, v1)
        bottom_pt = [(xA+xB)*0.5*ratio, max(yA, yB)*ratio] # (u2, v2)
        bigger_frame_reproject = cv.circle(bigger_frame_reproject, (int(bottom_pt[0]), int(bottom_pt[1])), 5, (0,255,0), thickness=3, lineType=8, shift=0) 
        bigger_frame_reproject = cv.circle(bigger_frame_reproject, (int(head_pt[0]), int(head_pt[1])), 5, (0,255,0), thickness=3, lineType=8, shift=0) 

        print("bottom_pt: ", bottom_pt)
        bp = np.zeros((1, 2), np.float32)
        bp[0][0] = bottom_pt[0]
        bp[0][1] = bottom_pt[1]
        #print("calib_corners: ", calib_corners[0])
        dst = cv.undistortPoints(bp.reshape(-1,1,2).astype(np.float32), camera_matrix_manual, dist_coefs_manual)
        bottom_pt = dst[0][0]
        # according to the formula: s1=1.7*r33+s2, s2=1.7*(r23-v1*r33)/(v1-v2)
        #s2 = 1.7*(rot[1][2]-head_pt[1]*rot[2][2])/(head_pt[1]-bottom_pt[1])
        print("bottom_pt after undistort: ", bottom_pt)
        #bottom_pt_center_normalized = (bottom_pt[0]-camera_matrix_manual[0][2], bottom_pt[1]-camera_matrix_manual[1][2])
        #print("bottom_pt_center_normalized: ", bottom_pt_center_normalized)        
        #s1 = 1.7*rot[2][2]+s2

        #print("ref_tvec: ", ref_tvec[0][0], ref_tvec[1][0], ref_tvec[2][0])
        Tz = rot[0][2]*ref_tvec[0][0]+rot[1][2]*ref_tvec[1][0]+rot[2][2]*ref_tvec[2][0]
        dz = rot[0][2]*bottom_pt[0]+rot[1][2]*bottom_pt[1]+rot[2][2]*1
        s2 = Tz/dz
        print("s2: ", s2)

        img_pt = np.array([[bottom_pt[0]], [bottom_pt[1]], [1]])
        #print("zz: ", s2*img_pt-ref_tvec)
        #print("tra: ", cv.transpose(rot))
        result = np.matmul(cv.transpose(rot), s2*img_pt-ref_tvec)
        print("result: ",cv.transpose(result))

        center = (int(Size_of_w*0.5-result[1][0]*px_of_meter), int(result[0][0]*px_of_meter+Size_of_w*0.5))     
        print("world XY: ", result[0][0], result[1][0])    
        print("window XY: ", center[0], center[1])
        #print("result: ", result)
        pchar = "[" + str(round_to_1(result[0][0])) + ", " + str(round_to_1(result[1][0])) + "]"

        Lmap_localized = cv.circle(Lmap_localized, center, 5, (255,0,0), thickness=3, lineType=8, shift=0) 
        cv.putText(Lmap_localized, pchar, center, cv.FONT_HERSHEY_COMPLEX, 0.5, (0,255,0), 1) 

        #Project the resulting 3d point onto 2d image again for comfirmation.
        imgpts, jac = cv.projectPoints(np.array([[result[0][0], result[1][0], result[2][0]], [0.0, 0.0, 0.0]]), ref_rvec, ref_tvec, camera_matrix_manual, dist_coefs_manual)
        intpt =  (int(imgpts[0][0][0]), int(imgpts[0][0][1]))
        print("intpt: ", intpt)

        if intpt[0]>0 and intpt[0]<bigger_frame_reproject.shape[1] and intpt[1]>0 and intpt[1]<bigger_frame_reproject.shape[0]:
            bigger_frame_reproject = cv.circle(bigger_frame_reproject, intpt, 5, (255,0,0), thickness=3, lineType=8, shift=0) 
            cv.putText(bigger_frame_reproject, pchar, (intpt[0], intpt[1]+30), cv.FONT_HERSHEY_COMPLEX, 0.8, (255,0,0), 2)         

    return Lmap_localized, bigger_frame_reproject

def create_camera_model(camera_matrix, width, height, scale_focal, draw_frame_axis=True):
    fx = camera_matrix[0,0]
    fy = camera_matrix[1,1]
    focal = 2 / (fx + fy)
    f_scale = scale_focal * focal

    print("f_scale: ", f_scale)

    # draw image plane
    X_img_plane = np.ones((4,5))
    X_img_plane[0:3,0] = [-width, height, f_scale]
    X_img_plane[0:3,1] = [width, height, f_scale]
    X_img_plane[0:3,2] = [width, -height, f_scale]
    X_img_plane[0:3,3] = [-width, -height, f_scale]
    X_img_plane[0:3,4] = [-width, height, f_scale]

    # draw triangle above the image plane
    X_triangle = np.ones((4,3))
    X_triangle[0:3,0] = [-width, -height, f_scale]
    X_triangle[0:3,1] = [0, -2*height, f_scale]
    X_triangle[0:3,2] = [width, -height, f_scale]

    # draw camera
    X_center1 = np.ones((4,2))
    X_center1[0:3,0] = [0, 0, 0]
    X_center1[0:3,1] = [-width, height, f_scale]

    X_center2 = np.ones((4,2))
    X_center2[0:3,0] = [0, 0, 0]
    X_center2[0:3,1] = [width, height, f_scale]

    X_center3 = np.ones((4,2))
    X_center3[0:3,0] = [0, 0, 0]
    X_center3[0:3,1] = [width, -height, f_scale]

    X_center4 = np.ones((4,2))
    X_center4[0:3,0] = [0, 0, 0]
    X_center4[0:3,1] = [-width, -height, f_scale]

    # draw camera frame axis
    X_frame1 = np.ones((4,2))
    X_frame1[0:3,0] = [0, 0, 0]
    X_frame1[0:3,1] = [f_scale*2, 0, 0]

    X_frame2 = np.ones((4,2))
    X_frame2[0:3,0] = [0, 0, 0]
    X_frame2[0:3,1] = [0, f_scale*2, 0]

    X_frame3 = np.ones((4,2))
    X_frame3[0:3,0] = [0, 0, 0]
    X_frame3[0:3,1] = [0, 0, f_scale*2]

    if draw_frame_axis:
        return [X_img_plane, X_triangle, X_center1, X_center2, X_center3, X_center4, X_frame1, X_frame2, X_frame3]
    else:
        return [X_img_plane, X_triangle, X_center1, X_center2, X_center3, X_center4]

def create_board_model(extrinsics, board_width, board_height, square_size, draw_frame_axis=True):
    width = board_width*square_size
    height = board_height*square_size

    # draw calibration board
    X_board = np.ones((4,5))
    #X_board_cam = np.ones((extrinsics.shape[0],4,5))
    X_board[0:3,0] = [0,0,0]
    X_board[0:3,1] = [width,0,0]
    X_board[0:3,2] = [width,height,0]
    X_board[0:3,3] = [0,height,0]
    X_board[0:3,4] = [0,0,0]

    # draw board frame axis
    X_frame1 = np.ones((4,2))
    X_frame1[0:3,0] = [0, 0, 0]
    X_frame1[0:3,1] = [height, 0, 0]

    X_frame2 = np.ones((4,2))
    X_frame2[0:3,0] = [0, 0, 0]
    X_frame2[0:3,1] = [0, height, 0]

    X_frame3 = np.ones((4,2))
    X_frame3[0:3,0] = [0, 0, 0]
    X_frame3[0:3,1] = [0, 0, height]

    if draw_frame_axis:
        return [X_board, X_frame1, X_frame2, X_frame3]
    else:
        return [X_board]

def draw_camera_boards(ax, camera_matrix, cam_width, cam_height, scale_focal,
                       extrinsics, board_width, board_height, square_size,
                       patternCentric):
    min_values = np.zeros((3,1))
    min_values = np.inf
    max_values = np.zeros((3,1))
    max_values = -np.inf

    if patternCentric:
        X_moving = create_camera_model(camera_matrix, cam_width, cam_height, scale_focal)
        #print("X_moving(camera): ", X_moving)
        X_static = create_board_model(extrinsics, board_width, board_height, square_size)
        #print("X_static(board): ", X_static)
    else:
        X_static = create_camera_model(camera_matrix, cam_width, cam_height, scale_focal, True)
        #print("X_static(board): ", X_static)
        X_moving = create_board_model(extrinsics, board_width, board_height, square_size)
        #print("X_moving(camera): ", X_moving)

    cm_subsection = linspace(0.0, 1.0, extrinsics.shape[0])
    colors = [ cm.jet(x) for x in cm_subsection ]

    #Plot the camera
    for i in range(len(X_static)):
        X = np.zeros(X_static[i].shape)
        for j in range(X_static[i].shape[1]):
            X[:,j] = transform_to_matplotlib_frame(np.eye(4), X_static[i][:,j])
        ax.plot3D(X[0,:], X[1,:], X[2,:], color='r')
        #print("printing red pt at:", X[0,:], X[1,:], X[2,:])
        min_values = np.minimum(min_values, X[0:3,:].min(1))
        max_values = np.maximum(max_values, X[0:3,:].max(1))

    #Plot the board
    for idx in range(extrinsics.shape[0]):
        R, _ = cv.Rodrigues(extrinsics[idx,0:3])
        cMo = np.eye(4,4)
        cMo[0:3,0:3] = R
        cMo[0:3,3] = extrinsics[idx,3:6]
        for i in range(len(X_moving)):
            X = np.zeros(X_moving[i].shape)
            for j in range(X_moving[i].shape[1]):
                X[0:4,j] = transform_to_matplotlib_frame(cMo, X_moving[i][0:4,j], patternCentric)
                # if i == 0 and j == 0:
                #     print(X[0:4,j])
            ax.plot3D(X[0,:], X[1,:], X[2,:], color=colors[idx])
            if i==0:
                print(X[:,0])
            min_values = np.minimum(min_values, X[0:3,:].min(1))
            max_values = np.maximum(max_values, X[0:3,:].max(1))

    return min_values, max_values

cap = cv.VideoCapture('rtsp://admin:h0940232@172.18.9.100/Streaming/Channels/1')
#cap = cv.VideoCapture('sample.MOV')
#cap = cv2.VideoCapture('rtsp://172.18.9.99/axis-media/media.amp')
#time.sleep(5)
#print(cv2.__version__)

kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE,(5,5))
kernel2 = cv.getStructuringElement(cv.MORPH_ELLIPSE,(7,7))
#fgbg = cv.bgsegm.createBackgroundSubtractorGMG()
#Threshold on the squared Mahalanobis distance between the pixel and the model to decide whether a pixel is well described by
#the background model. This parameter does not affect the background update.
bg_history_frame=500
fgbg = cv.createBackgroundSubtractorMOG2(history=500, varThreshold=8, detectShadows=False)
#fgbg = cv.bgsegm.createBackgroundSubtractorGMG()t
detector = cv.SimpleBlobDetector_create()
connectivity = 4
min_thresh=800
max_thresh=10000

IsVanishingCalibration=False

if IsVanishingCalibration:
    cv.namedWindow("frame")
    cv.moveWindow("frame", 40,10)
    cv.namedWindow("fgmask")
    cv.moveWindow("fgmask", 720,10)
    cv.namedWindow("axis")
    cv.moveWindow("axis", 40,420)

line_db_need_to_collect=100000 # set lower for debug purpose
line_db = []
contour_area_min=600

camera_matrix_manual = np.zeros((3, 3), np.float32)
camera_matrix_manual[0, 0] = 1009.60665
#camera_matrix_manual[1, 0] = 0
#camera_matrix_manual[2, 0] = 0
#camera_matrix_manual[0, 1] = 0
camera_matrix_manual[1, 1] = 1009.32417
#camera_matrix_manual[2, 1] = 0
camera_matrix_manual[0, 2] = 651.53609
camera_matrix_manual[1, 2] = 336.868
camera_matrix_manual[2, 2] = 1

dist_coefs_manual = np.zeros((1, 8), np.float32)     
dist_coefs_manual[0, 0] = -6.08059316
dist_coefs_manual[0, 1] = 9.70169024
dist_coefs_manual[0, 2] = 1.60141342e-03
dist_coefs_manual[0, 3] = -6.39510521e-05 
dist_coefs_manual[0, 4] = -1.77135020  
dist_coefs_manual[0, 5] = -5.71916015  
dist_coefs_manual[0, 6] = 7.55768940  
dist_coefs_manual[0, 7] = 1.36953813  

pattern_size = (4, 3)
square_size = 0.06395
pattern_points = np.zeros((np.prod(pattern_size), 3), np.float32)
pattern_points[:, :2] = np.indices(pattern_size).T.reshape(-1, 2)
pattern_points *= square_size
term = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_COUNT, 30, 0.1)
FinishCalibration = False
ref_rvec=None
ref_tvec=None

def draw(img, corners, imgpts):
    corner = tuple(corners[0].ravel())
    img = cv.line(img, corner, tuple(imgpts[0].ravel()), (0,0,255), 3)
    img = cv.line(img, corner, tuple(imgpts[1].ravel()), (0,255,0), 3)
    img = cv.line(img, corner, tuple(imgpts[2].ravel()), (255,0,0), 3)
    return img


#line in form of y=ax+c , so a tuple (a, c)
#return (IsHavingIntersection, inter_x, inter_y)
def find_two_line_intersection(line1, line2):
    if line1[0] == line2[0]:
        #print("The line are parallel!")
        return (False, -1, -1)
    else:
        a = line1[0]
        c = line1[1]
        b = line2[0]
        d = line2[1]
        return (True, (d-c)/(a-b), (a*d-b*c)/(a-b))


calib_corners = None
calib_imgpt = None
axis = np.float32([[0.5,0,0], [0,0.5,0], [0,0,-0.5]]).reshape(-1,3)
frame_num=0
hog = cv.HOGDescriptor()
hog.setSVMDetector( cv.HOGDescriptor_getDefaultPeopleDetector() )
while(cap.isOpened() and len(line_db)<line_db_need_to_collect):
    frame_num = frame_num+1
    start = time.time()
    ret, frame = cap.read()
    if ret == False:
        break
    #print("cap.read() took {} seconds.".format(time.time() - start))
    start = time.time()
    #cv2.putText(frame, str(datetime.datetime.now()), (210, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 0, 0), 2, 2)
    #time.sleep(0.055)

    if IsVanishingCalibration:
        fgmask = fgbg.apply(frame)

        # erosion followed by dilation. 
        fgmask = cv.morphologyEx(fgmask, cv.MORPH_OPEN, kernel)
        fgmask = cv.dilate(fgmask,kernel2,iterations = 1)

        # output = cv.connectedComponentsWithStats(fgmask, connectivity, cv.CV_32S)
        # for i in range(output[0]):
        #     if output[2][i][4] >= min_thresh and output[2][i][4] <= max_thresh:
        #         cv.rectangle(fgmask, (output[2][i][0], output[2][i][1]), (
        #             output[2][i][0] + output[2][i][2], output[2][i][1] + output[2][i][3]), (255, 255, 255), 2)
        # cv.imshow('detection', fgmask)

        #keypoints = detector.detect(fgmask)
        #im_with_keypoints = cv.drawKeypoints(fgmask, keypoints, np.array([]), (255,255,255), cv.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)

        thrhd_value = 1
        ret,fg_cnt_fitline = cv.threshold(fgmask,thrhd_value,255,cv.THRESH_BINARY)
        rows,cols = fg_cnt_fitline.shape[:2]
        im2, contours,hierarchy = cv.findContours(fg_cnt_fitline,cv.RETR_TREE,cv.CHAIN_APPROX_SIMPLE)
        #print("Number of contours: {}".format(len(contours)))

        fg_cnt_fitline_display = cv.cvtColor(fg_cnt_fitline,cv.COLOR_GRAY2RGB)

        for cnt in contours:
            area = cv.contourArea(cnt)
            if area > contour_area_min:
                rect = cv.minAreaRect(cnt)
                #rect_height = rect[1][1]
                #rect_width = rect[1][0]
                box = cv.boxPoints(rect)
                min_y = 99999
                min_x = 99999
                max_y = -99999
                max_x = -99999
                for pt in box:
                    if pt[1] < min_y:
                        min_y = pt[1]
                    if pt[1] > max_y:
                        max_y = pt[1]
                    if pt[0] < min_x:
                        min_x = pt[0]
                    if pt[0] > max_x:
                        max_x = pt[0]                    

                rect_height = max_y-min_y
                rect_width = max_x-min_x
                #Standing pedestrian must be tall rectangle
                if rect_height > rect_width*2.0:

                    
                    boxx = np.int0(box)
                    fg_cnt_fitline_display = cv.drawContours(fg_cnt_fitline_display,[boxx],0,(0,0,255),2)



                    [vx,vy,x,y] = cv.fitLine(cnt, cv.DIST_L2,0,0.01,0.01)

                    # y=ax+c, a tuple (a, c)
                    line_in_slope_form = (vy/vx, y-(vy/vx)*x)
                    if line_in_slope_form[0] != 0:
                        if frame_num > bg_history_frame:
                            line_db.append(line_in_slope_form)
                        
                        min_y_x = (min_y-line_in_slope_form[1])/line_in_slope_form[0]
                        max_y_x = (max_y-line_in_slope_form[1])/line_in_slope_form[0]
                        fg_cnt_fitline_display = cv.line(fg_cnt_fitline_display,(min_y_x,min_y),(max_y_x,max_y),(0,255,0),2)

        resized_frame = cv.resize(frame, (0,0), fx=0.5, fy=0.5) 
        resized_fgmask = cv.resize(fgmask, (0,0), fx=0.5, fy=0.5) 
        resized_fitline = cv.resize(fg_cnt_fitline_display, (0,0), fx=0.5, fy=0.5) 
        #imgBoth = np.hstack((resized_frame,resized_fgmask))
        #cv.imshow('frame',resized_frame)

        # f = plt.figure()
        # f.add_subplot(1,2, 1)
        # plt.imshow(resized_frame)
        # f.add_subplot(1,2, 2)
        # plt.imshow(resized_fgmask)
        # plt.show(block=True)


    if frame.any() and not FinishCalibration:
        fitting_error=[]
        frame_gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        extrinsics = None
        CanStillFound = True
        DetectedChessBoardnum=0
        while CanStillFound:
            #cv.imwrite("zzzz.png", frame_gray)
            found, corners = cv.findChessboardCorners(frame_gray, pattern_size,  flags=cv.CALIB_CB_ADAPTIVE_THRESH + cv.CALIB_CB_NORMALIZE_IMAGE + cv.CALIB_CB_FAST_CHECK)
            if found:
                DetectedChessBoardnum = DetectedChessBoardnum + 1
                obj_points = []
                img_points = []   
                #print("corners:", corners)
                
                cv.cornerSubPix(frame_gray, corners, (5, 5), (-1, -1), term)
                #print("corners:", corners)
                chessboards = [(corners.reshape(-1, 2), pattern_points)]

                chessboards = [x for x in chessboards if x is not None]
                for (corners, pattern_points) in chessboards:
                    img_points.append(corners)
                    obj_points.append(pattern_points)

                # calculate camera distortion
                h, w = frame_gray.shape[:2]  # TODO: use imquery call to retrieve results
                #rms, camera_matrix, dist_coefs, rvecs, tvecs = cv.calibrateCamera(obj_points, img_points, (w, h), cameraMatrix=camera_matrix_manual, distCoeffs=dist_coefs_manual, flags=cv.CALIB_USE_INTRINSIC_GUESS+ cv.CALIB_FIX_K1+ cv.CALIB_FIX_K2+ cv.CALIB_FIX_K3+ cv.CALIB_FIX_K4+ cv.CALIB_FIX_K5)
                #print(img_points[0][0])
                returnval, rvecs, tvecs = cv.solvePnP(np.array(obj_points), np.array(img_points),camera_matrix_manual, dist_coefs_manual )

                if img_points[0][0][0] > 640:
                    ref_rvec = rvecs
                    ref_tvec = tvecs
                    print("Calibration result is: ", ref_rvec, ref_tvec)
                    print(axis)
                    imgpts2, jac2 = cv.projectPoints(axis, rvecs, tvecs, camera_matrix_manual, dist_coefs_manual)
                    calib_corners = corners
                    calib_imgpt = imgpts2
                    frame = draw(frame,calib_corners,calib_imgpt)

                imgpts, jac = cv.projectPoints(np.array(obj_points), rvecs, tvecs, camera_matrix_manual, dist_coefs_manual)
                #print(imgpts[0][0])

                totalfittingerror=0
                for zz in range(len(imgpts)):
                    totalfittingerror = totalfittingerror + math.sqrt(math.pow(imgpts[zz][0][0]-img_points[0][zz][0], 2)+math.pow(imgpts[zz][0][1]-img_points[0][zz][1], 2))
                fitting_error.append(totalfittingerror)
                #print("totalfittingerror: ", totalfittingerror)



                #print("\nRMS:", rms)
                #print("camera matrix:\n", camera_matrix)
                #print("distortion coefficients: ", dist_coefs.ravel())     

                # brings the calibration pattern from the model coordinate space (in which object points are specified)
                # to the world coordinate space, that is, a real position of the calibration pattern
                # from chessboard (0, 0, 0) to 
                print("rotation: ",  [x* 180.0 / math.pi for x in rvecs])
                print("translation: ", cv.transpose(tvecs))     

                ext = cv.hconcat([np.array(cv.transpose(rvecs)), np.array(cv.transpose(tvecs))])
                print("ext: ", ext)

                if DetectedChessBoardnum == 1:
                    extrinsics = ext
                else:
                    extrinsics = np.vstack((extrinsics, ext))

                cv.drawChessboardCorners(frame, pattern_size, corners, found)

                #mask out the current chessboard
                x,y,w,h = cv.boundingRect(corners)
                cv.rectangle(frame_gray,(x-10,y-10),(x+w+10,y+h+10),255,-1)
                cv.putText(frame, str(DetectedChessBoardnum), (x, y), cv.FONT_HERSHEY_COMPLEX, 2, (0,255,0), 5) 
                # cv.imshow('masked chessboard', frame_gray)
                # cv.waitKey(0)                
            
            else:
                print("Cannot find any chessboard! break!")
                CanStillFound = False
                break



        if DetectedChessBoardnum > 0:
            board_width = 5
            board_height = 4
            square_size = 0.064

            fig = plt.figure()
            ax = fig.gca(projection='3d')
            ax.set_aspect("equal")

            cam_width = 0.064*6
            cam_height = 0.048*6
            scale_focal = 300
            min_values, max_values = draw_camera_boards(ax, camera_matrix_manual.copy(), cam_width, cam_height,
                                                        scale_focal, extrinsics, board_width,
                                                        board_height, square_size, False)

            X_min = min_values[0]
            X_max = max_values[0]
            Y_min = min_values[1]
            Y_max = max_values[1]
            Z_min = min_values[2]
            Z_max = max_values[2]
            max_range = np.array([X_max-X_min, Y_max-Y_min, Z_max-Z_min]).max() / 2.0

            mid_x = (X_max+X_min) * 0.5
            mid_y = (Y_max+Y_min) * 0.5
            mid_z = (Z_max+Z_min) * 0.5
            ax.set_xlim(mid_x - max_range, mid_x + max_range)
            ax.set_ylim(mid_y - max_range, mid_y + max_range)
            ax.set_zlim(mid_z - max_range, mid_z + max_range)

            ax.set_xlabel('x')
            ax.set_ylabel('z')
            ax.set_zlabel('-y')
            ax.set_title('Extrinsic Parameters Visualization')

            for item in fitting_error:
                print("fitting error: ", item)
      
            FinishCalibration = True
            # cv.imshow('chessboard corners', frame)
            # cv.waitKey(0)   
            # plt.show()       

    ratio = 2.0
    if frame.any() and FinishCalibration:
        frame = draw(frame,calib_corners,calib_imgpt)
        resized_frame = cv.resize(frame, (0,0), fx=(1/ratio), fy=(1/ratio)) 
        rects, weight = hog.detectMultiScale(resized_frame, winStride=(8, 8), padding=(8,8), scale=1.05)
        
        found_filtered = []
        # kill bb that has low weight
        for qz in range(len(rects)):
            if weight[qz][0] > hog_threshold:
                found_filtered.append(rects[qz])

        # found_filtered = []
        # for ri, r in enumerate(rect):
        #     for qi, q in enumerate(rect):
        #         if ri != qi and inside(r, q):
        #             break
        #     else:
        #         found_filtered.append(r)
        # draw_detections(resized_frame, found_filtered, 3)
        found_filtered = np.array([[x, y, x + w, y + h] for (x, y, w, h) in found_filtered])
        pick = non_max_suppression(found_filtered, probs=None, overlapThresh=0.65)

        # draw the final bounding boxes
        for (xA, yA, xB, yB) in pick:
            cv.rectangle(resized_frame, (xA, yA), (xB, yB), (0, 255, 0), 2)        

        bigger_frame = cv.resize(resized_frame, (0,0), fx=ratio, fy=ratio) 
        #cv.imshow('pedestrian detection', bigger_frame)        

        Size_of_w=500
        physical_size=30
        Lmap = GetWindowWithAxis(Size_of_w, physical_size)
        Lmap_localized, bigger_frame_reproject = PrintLocalization(Lmap, bigger_frame, pick, ratio, Size_of_w, physical_size, camera_matrix_manual, dist_coefs_manual, ref_rvec, ref_tvec, calib_corners)

        cv.imshow('pedestrian detection', bigger_frame_reproject)        
        cv.imshow('localization', Lmap_localized)      

        #Pending for debug
        if IsEachFrameDebug and len(rects)>0:
            cv.waitKey(5000)

    #cv.imshow('fgmask',resized_fgmask)
    #cv.imshow('axis',resized_fitline)
    if cv.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv.destroyAllWindows()

print("Collected over {} major axis of pedestrian blob, start calculation...".format(line_db_need_to_collect))

#Allocate the voting space
voting_space={}
for line1 in line_db:
    for line2 in line_db:
        ret = find_two_line_intersection(line1, line2)
        if ret[0] == True:
            int_coord = (int(ret[1]), int(ret[2]))
            if int_coord in voting_space:
                voting_space[int_coord] = voting_space[int_coord]+1
            else:
                voting_space[int_coord] = 1

if voting_space:
    vote_coord = max(voting_space.items(), key=operator.itemgetter(1))[0]
    print("Finish voting the pixel level vanishing point, which is {}, have {} vote".format(vote_coord, voting_space[vote_coord]))
