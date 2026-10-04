cuda_tile.module @m {
  entry @copy(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %12 = store_view_tko weak %7, %11[%4] token=%8 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
