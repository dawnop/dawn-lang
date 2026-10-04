cuda_tile.module @m {
  entry @swiglu_act(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [4096], strides = [1] : tensor_view<4096xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<4096xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<4096xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = negf %7 : tile<128xf64>
    %10 = exp %9 : tile<128xf64>
    %11 = constant <f64: 1.0> : tile<128xf64>
    %12 = addf %11, %10 rounding<nearest_even> : tile<128xf64>
    %13 = divf %7, %12 rounding<nearest_even> : tile<128xf64>
    %14 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %15 = make_tensor_view %14, shape = [4096], strides = [1] : tensor_view<4096xf64, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(128), padding_value = zero, tensor_view<4096xf64, strides=[1]>, dim_map=[0]>
    %17, %18 = load_view_tko weak %16[%4] token=%8 : partition_view<tile=(128), padding_value = zero, tensor_view<4096xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %19 = mulf %13, %17 rounding<nearest_even> : tile<128xf64>
    %20 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %21 = make_tensor_view %20, shape = [4096], strides = [1] : tensor_view<4096xf64, strides=[1]>
    %22 = make_partition_view %21 : partition_view<tile=(128), padding_value = zero, tensor_view<4096xf64, strides=[1]>, dim_map=[0]>
    %23 = store_view_tko weak %19, %22[%4] token=%18 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<4096xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
