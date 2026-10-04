cuda_tile.module @m {
  entry @pack_roundtrip(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 32> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %7 = make_tensor_view %6, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %14 = pack %12 : tile<32xi32> -> tile<128xi8>
    %15 = constant <i32: 0> : tile<i32>
    %16 = addi %5, %15 : tile<i32>
    %17 = unpack %14 : tile<128xi8> -> tile<256xi4>
    %18 = pack %17 : tile<256xi4> -> tile<128xi8>
    %19 = unpack %18 : tile<128xi8> -> tile<32xi32>
    %20 = reshape %16 : tile<i32> -> tile<1xi32>
    %21 = broadcast %20 : tile<1xi32> -> tile<32xi32>
    %22 = iota : tile<32xi32>
    %23 = addi %21, %22 : tile<32xi32>
    %24 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %25 = broadcast %24 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %26 = offset %25, %23 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %27 = store_ptr_tko weak %26, %19 token=%13 : tile<32xptr<i32>>, tile<32xi32> -> token
    %28 = constant <i32: 512> : tile<i32>
    %29 = addi %5, %28 : tile<i32>
    %30 = unpack %14 : tile<128xi8> -> tile<64xi16>
    %31 = pack %30 : tile<64xi16> -> tile<128xi8>
    %32 = unpack %31 : tile<128xi8> -> tile<32xi32>
    %33 = reshape %29 : tile<i32> -> tile<1xi32>
    %34 = broadcast %33 : tile<1xi32> -> tile<32xi32>
    %35 = iota : tile<32xi32>
    %36 = addi %34, %35 : tile<32xi32>
    %37 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %38 = broadcast %37 : tile<1xptr<i32>> -> tile<32xptr<i32>>
    %39 = offset %38, %36 : tile<32xptr<i32>>, tile<32xi32> -> tile<32xptr<i32>>
    %40 = store_ptr_tko weak %39, %32 token=%27 : tile<32xptr<i32>>, tile<32xi32> -> token
    return
  }
}
