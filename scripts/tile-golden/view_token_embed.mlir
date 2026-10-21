cuda_tile.module @m {
  entry @view_token_embed(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %3 = offset %2, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %4 = make_tensor_view %3, shape = [64, 16], strides = [16, 1] : tensor_view<64x16xf64, strides=[16, 1]>
    %5 = make_gather_scatter_view %4 : gather_scatter_view<tile=(8x16), tensor_view<64x16xf64, strides=[16, 1]>, sparse_dim=0>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %7 = make_tensor_view %6, shape = [104], strides = [1] : tensor_view<104xi32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(8), padding_value = zero, tensor_view<104xi32, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(8), padding_value = zero, tensor_view<104xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<8xi32>, token
    %14, %15 = load_view_tko weak %5[%12, %1] token=%0 : gather_scatter_view<tile=(8x16), tensor_view<64x16xf64, strides=[16, 1]>, sparse_dim=0>, tile<8xi32>, tile<i32> -> tile<8x16xf64>, token
    %16 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %17 = make_tensor_view %16, shape = [104, 16], strides = [16, 1] : tensor_view<104x16xf64, strides=[16, 1]>
    %18 = make_partition_view %17 : partition_view<tile=(8x16), padding_value = zero, tensor_view<104x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %19, %20, %21 = get_tile_block_id : tile<i32>
    %22 = store_view_tko weak %14, %18[%9, %20] token=%0 : tile<8x16xf64>, partition_view<tile=(8x16), padding_value = zero, tensor_view<104x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
