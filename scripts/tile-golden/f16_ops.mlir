cuda_tile.module @m {
  entry @f16_ops(%arg0: tile<ptr<f16>>, %arg1: tile<ptr<f16>>, %arg2: tile<ptr<f16>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f16>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf16, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf16, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf16, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf16>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<f16>>
    %10 = make_tensor_view %9, shape = [1000], strides = [1] : tensor_view<1000xf16, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf16, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf16, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf16>, token
    %14 = addf %7, %12 rounding<nearest_even> : tile<128xf16>
    %15 = mulf %14, %7 rounding<nearest_even> : tile<128xf16>
    %16 = subf %15, %12 rounding<nearest_even> : tile<128xf16>
    %17 = assume div_by<16>, %arg2 : tile<ptr<f16>>
    %18 = make_tensor_view %17, shape = [1000], strides = [1] : tensor_view<1000xf16, strides=[1]>
    %19 = make_partition_view %18 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf16, strides=[1]>, dim_map=[0]>
    %20 = store_view_tko weak %16, %19[%4] token=%13 : tile<128xf16>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xf16, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
