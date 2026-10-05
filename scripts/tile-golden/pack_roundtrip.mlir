cuda_tile.module @m {
  entry @pack_roundtrip(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %9 = pack %7 : tile<32xi32> -> tile<128xi8>
    %10 = unpack %9 : tile<128xi8> -> tile<256xi4>
    %11 = pack %10 : tile<256xi4> -> tile<128xi8>
    %12 = unpack %11 : tile<128xi8> -> tile<32xi32>
    %13 = reshape %12 : tile<32xi32> -> tile<1x32xi32>
    %14 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %15 = make_tensor_view %14, shape = [2, 512], strides = [512, 1] : tensor_view<2x512xi32, strides=[512, 1]>
    %16 = make_partition_view %15 : partition_view<tile=(1x32), padding_value = zero, tensor_view<2x512xi32, strides=[512, 1]>, dim_map=[0, 1]>
    %17, %18, %19 = get_tile_block_id : tile<i32>
    %20 = constant <i32: 2> : tile<i32>
    %21 = muli %18, %20 : tile<i32>
    %22 = store_view_tko weak %13, %16[%21, %4] token=%8 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<2x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %23 = unpack %9 : tile<128xi8> -> tile<64xi16>
    %24 = pack %23 : tile<64xi16> -> tile<128xi8>
    %25 = unpack %24 : tile<128xi8> -> tile<32xi32>
    %26 = reshape %25 : tile<32xi32> -> tile<1x32xi32>
    %27 = constant <i32: 2> : tile<i32>
    %28 = muli %18, %27 : tile<i32>
    %29 = constant <i32: 1> : tile<i32>
    %30 = addi %28, %29 : tile<i32>
    %31 = store_view_tko weak %26, %16[%30, %4] token=%22 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<2x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
