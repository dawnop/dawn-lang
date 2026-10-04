cuda_tile.module @m {
  entry @global_ctl(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [128], strides = [1] : tensor_view<128xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [128], strides = [1] : tensor_view<128xf64, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %14 = addf %12, %7 rounding<nearest_even> : tile<128xf64>
    %15 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %16 = make_tensor_view %15, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %17 = make_partition_view %16 : partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %18 = constant <i32: 2> : tile<i32>
    %19 = muli %4, %18 : tile<i32>
    %20 = store_view_tko weak %14, %17[%19] token=%13 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %21 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %22 = make_tensor_view %21, shape = [128], strides = [1] : tensor_view<128xf64, strides=[1]>
    %23 = make_partition_view %22 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>
    %24, %25 = load_view_tko weak %23[%4] token=%20 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %26 = addf %24, %7 rounding<nearest_even> : tile<128xf64>
    %27 = constant <i32: 2> : tile<i32>
    %28 = muli %4, %27 : tile<i32>
    %29 = constant <i32: 1> : tile<i32>
    %30 = addi %28, %29 : tile<i32>
    %31 = store_view_tko weak %26, %17[%30] token=%25 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
